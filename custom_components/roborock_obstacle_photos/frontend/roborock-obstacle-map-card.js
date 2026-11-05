// Roborock Obstacle Map card: the vacuum map with a clickable pin for every
// obstacle the robot photographed. Served by the roborock_obstacle_photos
// integration; positions come from the map entity's calibration points.

const REFRESH_MS = 30 * 60 * 1000; // signed photo URLs last an hour
const MAX_ZOOM = 8;
const ICONS = {
  cat: "🐈",
  dog: "🐕",
  pet: "🐈",
  box: "📦",
  "pet waste": "💩",
  poop: "💩",
  shoes: "👟",
  cable: "🔌",
  "extension cord": "🔌",
  clothes: "👕",
};

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

class RoborockObstacleMapCard extends HTMLElement {
  static getStubConfig(hass) {
    const map = Object.keys(hass.states).find(
      (id) => id.startsWith("image.") && hass.states[id].attributes.calibration_points
    );
    return { map_entity: map || "image.your_vacuum_map_custom" };
  }

  setConfig(config) {
    if (!config.map_entity) throw new Error("Set map_entity to the vacuum map image (e.g. Roborock Custom Map's)");
    this._config = { show: "current", ...config };
    this._mode = this._config.show === "all" ? "all" : "current";
    this._vacuum = null;
    this._mapState = null;
    if (!this.shadowRoot) this._build();
  }

  set hass(hass) {
    this._hass = hass;
    const state = hass.states[this._config.map_entity];
    if (state && state !== this._mapState) {
      const first = !this._mapState;
      this._mapState = state;
      this._img.src = state.attributes.entity_picture;
      this._toMap = affineFromCalibration(state.attributes.calibration_points);
      // Photos are downloaded right after the map updates, so look twice.
      this._fetch();
      if (!first) setTimeout(() => this._fetch(), 20000);
    }
    if (!state) this._message(`Entity not found: ${this._config.map_entity}`);
  }

  connectedCallback() {
    this._timer = setInterval(() => this._fetch(), REFRESH_MS);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
  }

  // Zoom: wheel or pinch zooms around the pointer, drag pans, double-tap toggles.
  _setupZoom() {
    this._zoom = { s: 1, x: 0, y: 0 };
    const view = this._view;
    const pointers = new Map();
    let pinch = null;
    let moved = 0;

    view.addEventListener("wheel", (e) => {
      e.preventDefault();
      this._zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * 0.0015));
    }, { passive: false });
    view.addEventListener("dblclick", (e) => {
      if (this._zoom.s > 1) this._resetZoom();
      else this._zoomAt(e.clientX, e.clientY, 2.5);
    });
    view.addEventListener("pointerdown", (e) => {
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      moved = 0;
      if (pointers.size === 2) pinch = this._pinchState(pointers);
    });
    window.addEventListener("pointermove", (e) => {
      const last = pointers.get(e.pointerId);
      if (!last) return;
      const dx = e.clientX - last.x;
      const dy = e.clientY - last.y;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      moved += Math.abs(dx) + Math.abs(dy);
      if (pointers.size === 2 && pinch) {
        const next = this._pinchState(pointers);
        this._zoomAt(next.cx, next.cy, next.dist / pinch.dist);
        pinch = next;
      } else if (pointers.size === 1 && this._zoom.s > 1) {
        this._zoom.x += dx;
        this._zoom.y += dy;
        this._applyZoom();
      }
    });
    const release = (e) => {
      pointers.delete(e.pointerId);
      if (pointers.size < 2) pinch = null;
    };
    window.addEventListener("pointerup", release);
    window.addEventListener("pointercancel", release);
    // A drag or pinch should not also open the pin under the finger.
    view.addEventListener("click", (e) => {
      if (moved > 8) {
        e.stopPropagation();
        e.preventDefault();
      }
    }, true);
  }

  _pinchState(pointers) {
    const [a, b] = [...pointers.values()];
    return { cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2, dist: Math.hypot(a.x - b.x, a.y - b.y) || 1 };
  }

  _zoomAt(clientX, clientY, factor) {
    const rect = this._view.getBoundingClientRect();
    const z = this._zoom;
    const scale = Math.min(MAX_ZOOM, Math.max(1, z.s * factor));
    const k = scale / z.s;
    const px = clientX - rect.left;
    const py = clientY - rect.top;
    z.x = px - (px - z.x) * k;
    z.y = py - (py - z.y) * k;
    z.s = scale;
    this._applyZoom();
  }

  _resetZoom() {
    this._zoom = { s: 1, x: 0, y: 0 };
    this._applyZoom();
  }

  _applyZoom() {
    const z = this._zoom;
    const { width, height } = this._view.getBoundingClientRect();
    z.x = Math.min(0, Math.max(width - width * z.s, z.x));
    z.y = Math.min(0, Math.max(height - height * z.s, z.y));
    this._stage.style.transform = `translate(${z.x}px, ${z.y}px) scale(${z.s})`;
    this._stage.style.setProperty("--inv", 1 / z.s);
    this._view.style.touchAction = z.s > 1 ? "none" : "pan-y";
    this.shadowRoot.querySelector(".reset").hidden = z.s === 1;
  }

  getCardSize() {
    return 6;
  }

  _build() {
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        ha-card { overflow: hidden; }
        .header { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 12px 16px 8px; }
        .title { font-size: 1.1em; font-weight: 500; color: var(--primary-text-color); }
        .toggle { display: flex; border: 1px solid var(--divider-color); border-radius: 16px; overflow: hidden; }
        .toggle button { border: 0; background: none; color: var(--primary-text-color); padding: 4px 12px; font: inherit; font-size: 0.85em; cursor: pointer; }
        .toggle button.on { background: var(--primary-color); color: var(--text-primary-color, #fff); }
        .map { position: relative; margin: 0 8px 8px; overflow: hidden; touch-action: pan-y; cursor: grab; }
        .stage { position: relative; transform-origin: 0 0; }
        .stage img { display: block; width: 100%; height: auto; user-select: none; -webkit-user-drag: none; }
        .reset { position: absolute; top: 8px; right: 8px; z-index: 2; border: 0; border-radius: 16px; padding: 4px 10px;
                 background: var(--card-background-color); color: var(--primary-text-color); box-shadow: 0 1px 4px rgba(0,0,0,.4); cursor: pointer; }
        .pin { position: absolute; transform: translate(-50%, -50%) scale(var(--inv, 1)); width: 30px; height: 30px; border-radius: 50%;
               border: 2px solid #fff; background: var(--card-background-color); box-shadow: 0 1px 4px rgba(0,0,0,.45);
               font-size: 15px; line-height: 26px; text-align: center; padding: 0; cursor: pointer; }
        .pin.pet { background: #ffe0b2; }
        .pin.nophoto { opacity: .55; cursor: default; }
        .message { padding: 0 16px 12px; color: var(--secondary-text-color); font-size: 0.9em; }
        .overlay { position: fixed; inset: 0; background: rgba(0,0,0,.75); display: none; align-items: center; justify-content: center; z-index: 10; }
        .overlay.open { display: flex; }
        .photo { background: var(--card-background-color); border-radius: 12px; padding: 12px; max-width: min(90vw, 420px); text-align: center; }
        .photo img { width: 100%; border-radius: 8px; }
        .photo .caption { margin-top: 8px; color: var(--primary-text-color); }
        .photo .sub { color: var(--secondary-text-color); font-size: 0.85em; }
      </style>
      <ha-card>
        <div class="header">
          <div class="title"></div>
          <div class="toggle">
            <button data-mode="current">Last run</button><button data-mode="all">All photos</button>
          </div>
        </div>
        <div class="map">
          <div class="stage"><img alt="Vacuum map" draggable="false" /><div class="pins"></div></div>
          <button class="reset" hidden>Reset zoom</button>
        </div>
        <div class="message"></div>
      </ha-card>
      <div class="overlay"><div class="photo"><img alt="" /><div class="caption"></div><div class="sub"></div></div></div>
    `;
    this._view = root.querySelector(".map");
    this._stage = root.querySelector(".stage");
    this._img = root.querySelector(".stage img");
    root.querySelector(".reset").addEventListener("click", () => this._resetZoom());
    this._setupZoom();
    this._pins = root.querySelector(".pins");
    this._overlay = root.querySelector(".overlay");
    this._img.addEventListener("load", () => this._render());
    this._overlay.addEventListener("click", () => this._overlay.classList.remove("open"));
    root.querySelectorAll(".toggle button").forEach((button) =>
      button.addEventListener("click", () => {
        this._mode = button.dataset.mode;
        this._render();
      })
    );
  }

  async _fetch() {
    if (!this._hass) return;
    try {
      const vacuums = await this._hass.callWS({ type: "roborock_obstacle_photos/obstacles" });
      const wanted = this._config.vacuum;
      this._vacuum = vacuums.find((v) => !wanted || v.duid === wanted || v.name === wanted) || null;
      this._render();
    } catch (err) {
      this._message(`Could not load obstacles: ${err.message || err}`);
    }
  }

  _message(text) {
    this.shadowRoot.querySelector(".message").textContent = text;
  }

  _render() {
    const root = this.shadowRoot;
    root.querySelector(".title").textContent = this._config.title || this._vacuum?.name || "Obstacles";
    root.querySelectorAll(".toggle button").forEach((b) => b.classList.toggle("on", b.dataset.mode === this._mode));
    this._pins.replaceChildren();
    if (!this._vacuum) return this._message("No vacuum with obstacle photos found.");
    if (!this._toMap) return this._message("The map entity has no calibration points (use Roborock Custom Map's image).");
    const { naturalWidth: w, naturalHeight: h } = this._img;
    if (!w || !h) return;

    const items = this._mode === "all" ? this._vacuum.history : this._vacuum.current;
    for (const item of items) {
      const point = this._toMap(item.x, item.y);
      const pin = document.createElement("button");
      pin.className = `pin${item.is_pet ? " pet" : ""}${item.url ? "" : " nophoto"}`;
      pin.style.left = `${(point.x / w) * 100}%`;
      pin.style.top = `${(point.y / h) * 100}%`;
      pin.textContent = ICONS[item.label] || "⚠️";
      pin.title = `${item.label}${item.confidence ? ` (${item.confidence}%)` : ""}`;
      if (item.url) pin.addEventListener("click", () => this._open(item));
      this._pins.append(pin);
    }
    const pets = items.filter((i) => i.is_pet).length;
    this._message(
      items.length
        ? `${items.length} photographed obstacle${items.length === 1 ? "" : "s"}${pets ? `, ${pets} pet` : ""}. Tap a pin to see the photo.`
        : this._mode === "all" ? "No photos saved yet." : "No photographed obstacles on the current map."
    );
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
  description: "Vacuum map with a clickable pin for every obstacle and pet photo",
  preview: false,
});
