// Roborock Obstacle Map card: hosts a Xiaomi Vacuum Map Card and adds a
// clickable pin for every obstacle the robot photographed. Pins live inside
// that card's zoomable map layer, so they pan and zoom with the map.
// Served by the roborock_obstacle_photos integration.

const REFRESH_MS = 30 * 60 * 1000; // signed photo URLs last an hour
const ATTACH_MS = 1000;
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

// Styles injected into the hosted map card's shadow root.
const MAP_STYLES = `
  .rop-layer { position: absolute; left: 0; top: 0; width: 100%; pointer-events: none; z-index: 1; }
  .rop-pin { position: absolute; width: 30px; height: 30px; padding: 0; border-radius: 50%;
             transform: translate(-50%, -50%) scale(calc(1 / var(--scale, 1)));
             border: 2px solid #fff; background: var(--card-background-color, #fff);
             box-shadow: 0 1px 4px rgba(0,0,0,.45); font-size: 15px; line-height: 26px; text-align: center;
             pointer-events: auto; cursor: pointer; }
  .rop-pin.pet { background: #ffe0b2; }
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

class RoborockObstacleMapCard extends HTMLElement {
  // Visual editor, rendered by Home Assistant from this schema.
  static getConfigForm() {
    const labels = {
      show: "Pins shown by default",
      vacuum: "Vacuum",
      map_entity: "Map image",
      map_card: "Xiaomi Vacuum Map Card settings",
    };
    const helpers = {
      show: "The paw button on the map switches between these.",
      vacuum: "Name or ID; only needed with more than one vacuum.",
      map_entity: "Leave empty to use the map card's map. Needs calibration points.",
      map_card: "The hosted map card's own options (zones, rooms, buttons).",
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
    this._mapCardReady = createCard({ ...config.map_card }).then((card) => {
      this._mapCard = card;
      if (this._hass) card.hass = this._hass;
      this._host.replaceChildren(card);
      return card;
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
    this._timer = setInterval(() => this._fetch(), REFRESH_MS);
    // The map card renders asynchronously and may rebuild its map; keep pins attached.
    this._attachTimer = setInterval(() => this._attach(), ATTACH_MS);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
    clearInterval(this._attachTimer);
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
    this._toggle = document.createElement("button");
    this._toggle.className = "rop-toggle";
    this._toggle.addEventListener("click", () => {
      this._mode = MODES[(MODES.indexOf(this._mode) + 1) % MODES.length];
      this._render();
    });
    controls.append(this._toggle);
    this._image = image;
    image.addEventListener("load", () => this._render());
    this._render();
    return true;
  }

  async _fetch() {
    if (!this._hass) return;
    try {
      const vacuums = await this._hass.callWS({ type: "roborock_obstacle_photos/obstacles" });
      const wanted = this._config.vacuum;
      this._vacuum = vacuums.find((v) => !wanted || v.duid === wanted || v.name === wanted) || null;
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

customElements.define("roborock-obstacle-map-card", RoborockObstacleMapCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "roborock-obstacle-map-card",
  name: "Roborock Obstacle Map",
  description: "Xiaomi Vacuum Map Card with clickable obstacle and pet photo pins",
  preview: false,
});
