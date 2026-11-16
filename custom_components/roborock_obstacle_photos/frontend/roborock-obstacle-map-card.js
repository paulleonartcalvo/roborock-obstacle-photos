// Roborock Obstacle Map card: hosts a Xiaomi Vacuum Map Card and adds a
// clickable pin for every obstacle the robot photographed. Pins live inside
// that card's zoomable map layer, so they pan and zoom with the map.
// Served by the roborock_obstacle_photos integration.

const REFRESH_MS = 30 * 60 * 1000; // signed photo URLs last an hour
const ATTACH_MS = 1000;
const ROOMS_WAIT_MS = 3000; // longest wait for room outlines before showing the map without them
const REVEAL_MAX_MS = 8000; // show the map card even if its image never reports loading
const DRAG_PX = 8; // a press that moved further than this was a drag, not a tap
const MODES = ["current", "all", "off"];
const MODE_LABELS = { current: "Last run", all: "All photos", off: "Hidden" };
const ICONS = {
  cat: "🐾",
  dog: "🐾",
  pet: "🐾",
  box: "📦",
  "pet waste": "💩",
  poop: "💩",
  shoes: "👟",
  cable: "🔌",
  "extension cord": "🔌",
  clothes: "👕",
};

// Icons for the "By room" mode, picked by words in the room's name.
const ROOM_ICONS = [
  [/closet|wardrobe/i, "mdi:hanger"],
  [/guest.*bath|toilet|powder|wc/i, "mdi:toilet"],
  [/bath|shower/i, "mdi:shower"],
  [/guest.*bed/i, "mdi:bed-outline"],
  [/bed/i, "mdi:bed"],
  [/kitchen/i, "mdi:fridge-outline"],
  [/living|lounge|family/i, "mdi:sofa"],
  [/dining/i, "mdi:silverware-fork-knife"],
  [/office|study/i, "mdi:desk"],
  [/hall|corridor/i, "mdi:shoe-print"],
  [/entr|foyer|mud/i, "mdi:door"],
  [/laundry|utility/i, "mdi:washing-machine"],
];
const DEFAULT_MAP_MODES = [{ template: "vacuum_clean_zone" }, { template: "vacuum_goto" }];
const ROOM_TEMPLATE = "vacuum_clean_segment";

function roomIcon(name) {
  return ROOM_ICONS.find(([pattern]) => pattern.test(name))?.[1] || "mdi:floor-plan";
}

// Styles injected into the hosted map card's shadow root.
const MAP_STYLES = `
  .rop-layer { position: absolute; left: 0; top: 0; width: 100%; pointer-events: none; z-index: 1; }
  .rop-pin { position: absolute; width: 30px; height: 30px; padding: 0; border-radius: 50%;
             transform: translate(-50%, -50%) scale(calc(1 / var(--scale, 1)));
             border: 2px solid #fff; background: var(--card-background-color, #fff);
             box-shadow: 0 1px 4px rgba(0,0,0,.45); font-size: 15px; line-height: 26px; text-align: center;
             pointer-events: auto; cursor: pointer; }
  .rop-pin.pet { background: #ffe0b2; }
  .rop-layer.rop-busy .rop-pin { pointer-events: none; }
  .room-wrapper.selected > .room-outline { stroke-dasharray: none; }
  .rop-toggle { position: absolute; left: 8px; top: 8px; z-index: 2; border: 0; border-radius: 16px; padding: 4px 10px;
                background: var(--card-background-color, #fff); color: var(--primary-text-color, #000);
                box-shadow: 0 1px 4px rgba(0,0,0,.4); font: inherit; font-size: 0.85em; cursor: pointer; }
`;

// Solve map = A·vacuum + b from three calibration point pairs.
function affineFromCalibration(points) {
  if (!Array.isArray(points) || points.length < 3) return null;
  const [p0, p1, p2] = points;
  const det =
    p0.vacuum.x * (p1.vacuum.y - p2.vacuum.y) -
    p0.vacuum.y * (p1.vacuum.x - p2.vacuum.x) +
    (p1.vacuum.x * p2.vacuum.y - p2.vacuum.x * p1.vacuum.y);
  if (!det) return null;
  const solve = (axis) => {
    const [m0, m1, m2] = [p0.map[axis], p1.map[axis], p2.map[axis]];
    const a = (m0 * (p1.vacuum.y - p2.vacuum.y) - p0.vacuum.y * (m1 - m2) + (m1 * p2.vacuum.y - m2 * p1.vacuum.y)) / det;
    const b = (p0.vacuum.x * (m1 - m2) - m0 * (p1.vacuum.x - p2.vacuum.x) + (p1.vacuum.x * m2 - p2.vacuum.x * m1)) / det;
    const c = m0 - a * p0.vacuum.x - b * p0.vacuum.y;
    return { a, b, c };
  };
  const x = solve("x");
  const y = solve("y");
  return (vx, vy) => ({ x: x.a * vx + x.b * vy + x.c, y: y.a * vx + y.b * vy + y.c });
}

function formatTime(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

async function createCard(config) {
  if (window.loadCardHelpers) return (await window.loadCardHelpers()).createCardElement(config);
  const tag = config.type.replace(/^custom:/, "");
  await customElements.whenDefined(tag);
  const card = document.createElement(tag);
  card.setConfig(config);
  return card;
}

// The map card adds "&v=<now>" to the map image URL on every render, and it
// re-renders on every pan/zoom frame, so a drag restarts the image download
// each frame and the map goes blank until you let go. Keep the URL until the
// image itself changes (an image entity's state is its last-updated time).
function stabilizeMapSrc(card) {
  const original = card._getMapSrc;
  if (typeof original !== "function" || card._ropStableSrc) return;
  let key = null;
  let src = null;
  card._getMapSrc = function (preset) {
    const fresh = original.call(this, preset);
    const camera = preset?.map_source?.camera;
    const state = camera && this.hass?.states?.[camera];
    if (!state || typeof fresh !== "string" || !fresh.includes("&v=")) return fresh;
    const next = `${state.state}|${state.attributes.entity_picture}`;
    if (next !== key) {
      key = next;
      src = fresh;
    }
    return src;
  };
  card._ropStableSrc = true;
}

class RoborockObstacleMapCard extends HTMLElement {
  // Visual editor, rendered by Home Assistant from this schema.
  static getConfigForm() {
    const labels = {
      show: "Pins shown by default",
      vacuum: "Vacuum",
      map_entity: "Map image",
      map_card: "Xiaomi Vacuum Map Card settings",
      room_mode: "Add a \"By room\" mode",
    };
    const helpers = {
      show: "The paw button on the map switches between these.",
      vacuum: "Name or ID; only needed with more than one vacuum.",
      map_entity: "Leave empty to use the map card's map. Needs calibration points.",
      map_card: "The hosted map card's own options (zones, rooms, buttons).",
      room_mode: "Click rooms on the map to clean them. Outlines come from the robot's map and follow it when it changes.",
    };
    return {
      schema: [
        {
          name: "show",
          selector: {
            select: {
              mode: "dropdown",
              options: MODES.map((value) => ({ value, label: MODE_LABELS[value] })),
            },
          },
        },
        { name: "vacuum", selector: { text: {} } },
        { name: "map_entity", selector: { entity: { domain: "image" } } },
        { name: "room_mode", selector: { boolean: {} } },
        { name: "map_card", required: true, selector: { object: {} } },
      ],
      computeLabel: (field) => labels[field.name],
      computeHelper: (field) => helpers[field.name],
    };
  }

  static getStubConfig(hass) {
    const ids = Object.keys(hass.states);
    const map = ids.find((id) => id.startsWith("image.") && hass.states[id].attributes.calibration_points);
    const vacuum = ids.find((id) => id.startsWith("vacuum."));
    return {
      show: "current",
      map_card: {
        type: "custom:xiaomi-vacuum-map-card",
        vacuum_platform: "Roborock",
        entity: vacuum || "vacuum.your_vacuum",
        map_source: { camera: map || "image.your_vacuum_map_custom" },
        calibration_source: { camera: true },
      },
    };
  }

  setConfig(config) {
    if (!config.map_card) throw new Error("Set map_card to your xiaomi-vacuum-map-card config");
    const mapEntity = config.map_entity || config.map_card.map_source?.camera;
    if (!mapEntity) throw new Error("map_card needs map_source.camera (or set map_entity)");
    this._config = { show: "current", ...config, map_entity: mapEntity };
    this._mode = MODES.includes(this._config.show) ? this._config.show : "current";
    this._mapState = null;
    if (!this.shadowRoot) this._build();
    // Home Assistant re-sends the config now and then; rebuilding the map card
    // would blank the map and lose its zoom, so only rebuild when it changed.
    const key = JSON.stringify([config.map_card, config.room_mode]);
    if (key === this._configKey) return;
    this._configKey = key;
    this._mapConfig = JSON.stringify(config.map_card);
    this._roomsKey = null;
    this._scheduleBuild();
  }

  // With the room mode on, wait for the room outlines so the map and its rooms
  // appear together instead of the map being rebuilt a moment later.
  _scheduleBuild() {
    clearTimeout(this._buildTimer);
    if (!this._config.room_mode) {
      this._buildMapCard();
    } else if (this._vacuum) {
      this._syncRooms();
    } else {
      this._buildTimer = setTimeout(() => {
        if (this._roomsKey === null) {
          this._roomsKey = "";
          this._buildMapCard();
        }
      }, ROOMS_WAIT_MS);
    }
  }

  // The hosted card's config, plus a "By room" mode drawn from the robot's map.
  _hostedConfig() {
    const config = JSON.parse(this._mapConfig);
    const rooms = this._config.room_mode ? this._vacuum?.rooms : null;
    if (!rooms?.length) return config;
    const options = typeof this._config.room_mode === "object" ? this._config.room_mode : {};
    const names = this._hass?.states?.[this._config.map_entity]?.attributes?.rooms || {};
    const selections = rooms.map((room) => {
      const name = names[room.id]?.name || names[String(room.id)]?.name || `Room ${room.id}`;
      const [x, y] = room.label;
      const selection = { id: room.id, outline: room.outline, label: { text: name, x, y, offset_y: 0 } };
      // Icons are opt-in: a name label per room is quieter.
      if (options.show_icons || options.icons?.[name]) {
        selection.icon = { name: options.icons?.[name] || roomIcon(name), x, y };
        selection.label.offset_y = 35;
      }
      return selection;
    });
    const modes = config.map_modes ? [...config.map_modes] : [...DEFAULT_MAP_MODES];
    const mode = {
      template: ROOM_TEMPLATE,
      name: options.name || "By room",
      icon: options.icon || "mdi:floor-plan",
      predefined_selections: selections,
    };
    const existing = modes.findIndex((m) => m.template === ROOM_TEMPLATE && !m.predefined_selections?.length);
    if (existing >= 0) modes[existing] = { ...mode, ...modes[existing], predefined_selections: selections };
    else if (options.default === false) modes.push(mode);
    else modes.unshift(mode); // the card starts in its first mode
    return { ...config, map_modes: modes };
  }

  // Rebuild the hosted card when the rooms (or their names) change.
  _syncRooms() {
    if (!this._config.room_mode || !this._vacuum) return;
    const names = this._hass?.states?.[this._config.map_entity]?.attributes?.rooms || {};
    const key = JSON.stringify([this._vacuum.rooms || [], Object.entries(names).map(([id, r]) => [id, r?.name])]);
    if (key === this._roomsKey) return;
    clearTimeout(this._buildTimer);
    this._roomsKey = key;
    this._buildMapCard();
  }

  // Lift the loading cover once the map image is in, so the buttons, the map and
  // its rooms appear together.
  _reveal() {
    clearTimeout(this._revealTimer);
    this._cover?.remove();
    this._cover = null;
  }

  _buildMapCard() {
    createCard(this._hostedConfig()).then((card) => {
      // A card whose script loads late asks its parent to rebuild it.
      card.addEventListener("ll-rebuild", (e) => {
        e.stopPropagation();
        this._buildMapCard();
      }, { once: true });
      stabilizeMapSrc(card);
      this._mapCard = card;
      if (this._hass) card.hass = this._hass;
      const wrapper = document.createElement("div");
      wrapper.className = "card-wrap";
      wrapper.append(card);
      if (!this._shown) {
        // First load: cover the card, at exactly its size, until its map is in.
        this._shown = true;
        this._cover = document.createElement("div");
        this._cover.className = "cover";
        this._cover.innerHTML = "<span>Loading map…</span>";
        wrapper.append(this._cover);
        this._revealTimer = setTimeout(() => this._reveal(), REVEAL_MAX_MS);
      }
      this._host.replaceChildren(wrapper);
    });
  }

  set hass(hass) {
    this._hass = hass;
    if (this._mapCard) this._mapCard.hass = hass;
    const state = hass.states[this._config.map_entity];
    if (state && state !== this._mapState) {
      const first = !this._mapState;
      this._mapState = state;
      this._toMap = affineFromCalibration(state.attributes.calibration_points);
      // Photos are downloaded right after the map updates, so look twice.
      this._fetch();
      if (!first) setTimeout(() => this._fetch(), 20000);
    }
  }

  connectedCallback() {
    // Removed from the page while waiting for the rooms: start waiting again.
    if (this._config && !this._mapCard && this._roomsKey === null) this._scheduleBuild();
    this._timer = setInterval(() => this._fetch(), REFRESH_MS);
    // The map card renders asynchronously and may rebuild its map; keep pins attached.
    this._attachTimer = setInterval(() => this._attach(), ATTACH_MS);
  }

  disconnectedCallback() {
    clearTimeout(this._buildTimer);
    clearTimeout(this._revealTimer);
    clearInterval(this._timer);
    clearInterval(this._attachTimer);
    this._endGesture();
  }

  getCardSize() {
    return this._mapCard?.getCardSize?.() ?? 8;
  }

  getGridOptions() {
    return { columns: "full", rows: "auto" };
  }

  _build() {
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host { display: block; }
        .card-wrap { position: relative; }
        .cover { position: absolute; inset: 0; z-index: 3; display: flex; align-items: center; justify-content: center;
                 border-radius: var(--ha-card-border-radius, 12px); color: var(--secondary-text-color);
                 background: var(--ha-card-background, var(--card-background-color, #fff)); }
        .cover span { animation: rop-pulse 1.4s ease-in-out infinite; }
        @keyframes rop-pulse { 0%, 100% { opacity: .45; } 50% { opacity: 1; } }
        .overlay { position: fixed; inset: 0; background: rgba(0,0,0,.75); display: none; align-items: center; justify-content: center; z-index: 10; }
        .overlay.open { display: flex; }
        .photo { background: var(--card-background-color); border-radius: 12px; padding: 12px; max-width: min(90vw, 420px); text-align: center; }
        .photo img { width: 100%; border-radius: 8px; }
        .photo .caption { margin-top: 8px; color: var(--primary-text-color); }
        .photo .sub { color: var(--secondary-text-color); font-size: 0.85em; }
      </style>
      <div class="host"></div>
      <div class="overlay"><div class="photo"><img alt="" /><div class="caption"></div><div class="sub"></div></div></div>
    `;
    this._host = root.querySelector(".host");
    this._overlay = root.querySelector(".overlay");
    this._overlay.addEventListener("click", () => this._overlay.classList.remove("open"));
  }

  // Put the pin layer and toggle into the map card; returns false until it has rendered.
  _attach() {
    const root = this._mapCard?.shadowRoot;
    const content = root?.getElementById("map-zoomer-content");
    const image = root?.getElementById("map-image");
    const controls = root?.getElementById("map-zoomer-overlay");
    if (!content || !image || !controls) return false;
    if (this._layer?.parentNode === content && this._toggle?.parentNode === controls && this._image === image) {
      return true;
    }
    if (!root.querySelector("style[data-rop]")) {
      const style = document.createElement("style");
      style.dataset.rop = "";
      style.textContent = MAP_STYLES;
      root.append(style);
    }
    this._layer?.remove();
    this._toggle?.remove();
    this._layer = document.createElement("div");
    this._layer.className = "rop-layer";
    content.append(this._layer);
    // The map card only hears moves and releases over its own drawing layer.
    // While a drag that started on the map (a zone, a pan) is in progress,
    // let the pointer pass through the pins so they can't swallow the release.
    if (this._content !== content) {
      this._content = content;
      content.addEventListener("pointerdown", (e) => {
        if (!e.target.closest?.(".rop-pin")) this._startGesture();
        // The first finger (or the mouse) starts a press; a second one makes it a pinch.
        if (e.isPrimary) this._down = { x: e.clientX, y: e.clientY, multi: false };
        else if (this._down) this._down.multi = true;
      }, true);
      // A pan or pinch that ends on a room would otherwise select it.
      content.addEventListener("click", (e) => {
        const down = this._down;
        if (!down) return;
        const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
        if (down.multi || moved > DRAG_PX) {
          e.stopPropagation();
          e.preventDefault();
        }
      }, true);
    }
    this._toggle = document.createElement("button");
    this._toggle.className = "rop-toggle";
    this._toggle.addEventListener("click", () => {
      this._mode = MODES[(MODES.indexOf(this._mode) + 1) % MODES.length];
      this._render();
    });
    controls.append(this._toggle);
    this._image = image;
    image.addEventListener("load", () => {
      this._reveal();
      this._render();
    });
    if (image.complete && image.naturalWidth) this._reveal();
    this._render();
    return true;
  }

  _startGesture() {
    this._layer?.classList.add("rop-busy");
    if (this._gestureEnd) return;
    // Wait a tick so the mouseup that follows pointerup still passes through.
    this._gestureEnd = () => setTimeout(() => this._endGesture());
    for (const type of ["pointerup", "pointercancel"]) window.addEventListener(type, this._gestureEnd, true);
  }

  _endGesture() {
    this._layer?.classList.remove("rop-busy");
    if (!this._gestureEnd) return;
    for (const type of ["pointerup", "pointercancel"]) window.removeEventListener(type, this._gestureEnd, true);
    this._gestureEnd = null;
  }

  async _fetch() {
    if (!this._hass) return;
    try {
      const vacuums = await this._hass.callWS({ type: "roborock_obstacle_photos/obstacles" });
      const wanted = this._config.vacuum;
      this._vacuum = vacuums.find((v) => !wanted || v.duid === wanted || v.name === wanted) || null;
      this._syncRooms();
      this._render();
    } catch (err) {
      console.warn("roborock-obstacle-map-card: could not load obstacles", err);
    }
  }

  _render() {
    if (!this._layer) return;
    const items = !this._vacuum || this._mode === "off"
      ? []
      : this._mode === "all" ? this._vacuum.history : this._vacuum.current;
    const pets = items.filter((i) => i.is_pet).length;
    this._toggle.textContent = `🐾 ${MODE_LABELS[this._mode]}${this._mode === "off" ? "" : ` (${pets || items.length})`}`;
    this._layer.replaceChildren();
    const { naturalWidth: w, naturalHeight: h } = this._image;
    if (!this._toMap || !w || !h) return;
    this._layer.style.aspectRatio = `${w} / ${h}`;

    for (const item of items) {
      if (!item.url) continue;
      const point = this._toMap(item.x, item.y);
      const pin = document.createElement("button");
      pin.className = `rop-pin${item.is_pet ? " pet" : ""}`;
      pin.style.left = `${(point.x / w) * 100}%`;
      pin.style.top = `${(point.y / h) * 100}%`;
      pin.textContent = ICONS[item.label] || "⚠️";
      pin.title = `${item.label}${item.confidence ? ` (${item.confidence}%)` : ""}`;
      // Keep the map from starting a pan or a zone selection under the pin.
      pin.addEventListener("pointerdown", (e) => e.stopPropagation());
      pin.addEventListener("mousedown", (e) => e.stopPropagation());
      pin.addEventListener("click", (e) => {
        e.stopPropagation();
        this._open(item);
      });
      this._layer.append(pin);
    }
  }

  _open(item) {
    const photo = this._overlay.querySelector(".photo");
    photo.querySelector("img").src = item.url;
    photo.querySelector(".caption").textContent =
      `${ICONS[item.label] || ""} ${item.label}${item.confidence ? ` · ${item.confidence}%` : ""}`;
    photo.querySelector(".sub").textContent = formatTime(item.captured_at);
    this._overlay.classList.add("open");
  }
}

if (!customElements.get("roborock-obstacle-map-card")) {
  customElements.define("roborock-obstacle-map-card", RoborockObstacleMapCard);
}
window.customCards = window.customCards || [];
window.customCards.push({
  type: "roborock-obstacle-map-card",
  name: "Roborock Obstacle Map",
  description: "Xiaomi Vacuum Map Card with clickable obstacle and pet photo pins",
  preview: false,
});
