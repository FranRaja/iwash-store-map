const statusLabels = {
  open: "Abierta",
  upcoming: "Próxima apertura"
};

let stores = [];
let markers = new Map();
let map = null;
let activeFilter = "all";
let selectedIndex = null;
let visible = [];
const cards = new Map();

function arrowIcon() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", "M5 12h14m-6-6 6 6-6 6");
  svg.append(path);
  return svg;
}

function selectStore(index, revealCard = false) {
  selectedIndex = index;
  cards.forEach((card, key) => {
    card.classList.toggle("selected", key === index);
    if (!card.disabled) card.setAttribute("aria-pressed", String(key === index));
  });
  markers.forEach((marker, key) => {
    marker.getElement()?.classList.toggle("is-selected", key === index);
    marker.setZIndexOffset(key === index ? 1000 : 0);
  });
  if (revealCard && window.matchMedia("(min-width: 761px)").matches) {
    cards.get(index)?.scrollIntoView({ block: "nearest" });
  }
}

function fitVisible() {
  const points = visible.filter(hasCoordinates).map(store => [store.lat, store.lng]);
  if (points.length) map.fitBounds(L.latLngBounds(points), { padding: [30, 30], maxZoom: 12 });
}

function normalize(value) {
  return Array.from(String(value || "").normalize("NFD"))
    .filter((char) => {
      const code = char.codePointAt(0);
      return code < 768 || code > 879;
    })
    .join("")
    .toLocaleLowerCase("es")
    .trim();
}

function hasCoordinates(store) {
  return Number.isFinite(store.lat) && Number.isFinite(store.lng);
}

function statusLabel(store) {
  return statusLabels[store.status] || "Estado no disponible";
}

function placeLabel(store) {
  return [store.city, store.province].filter(Boolean).join(", ");
}

function makeMarkerIcon(store) {
  const className = store.status === "upcoming" ? "iwash-marker upcoming" : "iwash-marker";
  return L.divIcon({
    className: "iwash-marker-icon",
    html: '<div class="' + className + '" aria-hidden="true"></div>',
    iconSize: [22, 22],
    iconAnchor: [11, 11],
    popupAnchor: [0, -12]
  });
}

function createPopup(store) {
  const root = document.createElement("div");
  root.className = "popup";

  const status = document.createElement("p");
  status.className = "popup-status" + (store.status === "open" ? " open" : "");
  status.textContent = statusLabel(store);
  root.append(status);

  const title = document.createElement("h2");
  title.textContent = store.name;
  root.append(title);

  if (store.address) {
    const address = document.createElement("p");
    address.textContent = store.address;
    root.append(address);
  }

  if (placeLabel(store)) {
    const place = document.createElement("p");
    place.className = "popup-place";
    place.textContent = placeLabel(store);
    root.append(place);
  }

  const query = store.address
    ? store.name + " " + store.address
    : store.lat + "," + store.lng;
  const directions = document.createElement("a");
  directions.className = "directions";
  directions.href = "https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent(query);
  directions.target = "_blank";
  directions.rel = "noopener noreferrer";
  directions.textContent = "Cómo llegar";
  directions.append(arrowIcon());
  root.append(directions);

  return root;
}

function createStoreCard(store, index) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = "store-card" + (hasCoordinates(store) ? " has-marker" : "");
  card.disabled = !hasCoordinates(store);
  card.setAttribute("aria-label", store.name + ", " + statusLabel(store) + ", " + (placeLabel(store) || "ubicación pendiente"));
  if (!card.disabled) card.setAttribute("aria-pressed", "false");

  const name = document.createElement("span");
  name.className = "store-name";
  name.textContent = store.name;
  card.append(name);

  const place = document.createElement("span");
  place.className = "store-place";
  place.textContent = placeLabel(store) || "Localidad por confirmar";
  card.append(place);

  const footer = document.createElement("span");
  footer.className = "store-footer";

  const badge = document.createElement("span");
  badge.className = "status-badge" + (store.status === "upcoming" ? " upcoming" : "");
  badge.textContent = statusLabel(store);
  footer.append(badge);

  if (!hasCoordinates(store)) {
    const pending = document.createElement("span");
    pending.className = "location-pending";
    pending.textContent = "Ubicación pendiente";
    footer.append(pending);
  }

  card.append(footer);

  if (hasCoordinates(store)) {
    const arrow = arrowIcon();
    arrow.classList.add("card-arrow");
    card.append(arrow);
    card.addEventListener("click", () => {
      const marker = markers.get(index);
      if (!marker || !map) return;
      selectStore(index);
      map.setView([store.lat, store.lng], 14);
      marker.openPopup();
      if (window.matchMedia("(max-width: 760px)").matches) {
        document.querySelector(".map-panel").scrollIntoView({ block: "start" });
      }
    });
  }

  cards.set(index, card);
  return card;
}

function visibleStores(query) {
  const term = normalize(query);
  return stores.filter((store) =>
    (activeFilter === "all" || store.status === activeFilter) &&
    (!term || [store.name, store.city, store.province].some((value) => normalize(value).includes(term)))
  );
}

function renderList(query = document.getElementById("searchInput").value) {
  const list = document.getElementById("storeList");
  const resultCount = document.getElementById("resultCount");
  const filtered = visibleStores(query);
  visible = filtered;
  map.closePopup();
  selectStore(null);
  cards.clear();
  list.replaceChildren();
  document.getElementById("clearSearch").hidden = !query;
  const located = filtered.filter(hasCoordinates).length;
  document.getElementById("mapNote").textContent = located
    ? located + (located === 1 ? " ubicación en el mapa" : " ubicaciones en el mapa")
    : filtered.length ? "Ubicación pendiente de confirmar" : "Sin resultados para esta búsqueda";

  resultCount.textContent = filtered.length === 1
    ? "1 tienda"
    : filtered.length + " tiendas";

  if (filtered.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No encontramos esa tienda. Prueba otra ciudad o provincia, o cambia el filtro de apertura.";
    list.append(empty);
  } else {
    filtered.forEach((store) => list.append(createStoreCard(store, stores.indexOf(store))));
  }

  markers.forEach((marker) => map.removeLayer(marker));
  filtered.forEach((store) => {
    const marker = markers.get(stores.indexOf(store));
    if (marker) marker.addTo(map);
  });
  list.scrollTop = 0;
  fitVisible();
}

function initializeMap() {
  map = L.map("map", {
    zoomControl: false,
    attributionControl: true,
    scrollWheelZoom: false
  }).setView([40.4168, -3.7038], 6);

  L.control.zoom({ position: "bottomright" }).addTo(map);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);

  stores.forEach((store, index) => {
    if (!hasCoordinates(store)) return;
    const marker = L.marker([store.lat, store.lng], { icon: makeMarkerIcon(store), title: store.name, alt: store.name })
      .bindPopup(createPopup(store));
    marker.on("add", () => marker.getElement()?.setAttribute("aria-label", store.name + ", " + statusLabel(store)));
    marker.on("popupopen", () => selectStore(index, true));
    marker.on("popupclose", () => { if (selectedIndex === index) selectStore(null); });
    markers.set(index, marker);
    marker.addTo(map);
  });
  new ResizeObserver(() => {
    map.invalidateSize({ pan: false });
    if (selectedIndex === null) fitVisible();
  }).observe(document.getElementById("map"));
}

async function start() {
  const status = document.getElementById("loadStatus");
  try {
    const response = await fetch("./stores.json", { cache: "no-store" });
    if (!response.ok) throw new Error("No se pudo cargar el directorio de tiendas.");
    const payload = await response.json();
    if (!Array.isArray(payload.stores) || payload.stores.length === 0) {
      throw new Error("El directorio no contiene tiendas.");
    }
    if (typeof L === "undefined") throw new Error("No se pudo cargar el mapa. Comprueba tu conexión.");

    stores = payload.stores;
    document.getElementById("openCount").textContent =
      String(stores.filter((store) => store.status === "open").length);
    document.getElementById("upcomingCount").textContent =
      String(stores.filter((store) => store.status === "upcoming").length);

    initializeMap();
    renderList("");
    document.querySelectorAll("#searchInput, [data-filter], #resetView").forEach(control => { control.disabled = false; });
    document.getElementById("searchInput").addEventListener("input", (event) => {
      renderList(event.target.value);
    });
    document.querySelectorAll("[data-filter]").forEach(button => button.addEventListener("click", () => {
      activeFilter = button.dataset.filter;
      document.querySelectorAll("[data-filter]").forEach(control => control.setAttribute("aria-pressed", String(control === button)));
      renderList();
    }));
    document.getElementById("clearSearch").addEventListener("click", () => {
      document.getElementById("searchInput").value = "";
      document.getElementById("searchInput").focus();
      renderList("");
    });
    document.getElementById("resetView").addEventListener("click", () => {
      document.getElementById("searchInput").value = "";
      activeFilter = "all";
      document.querySelectorAll("[data-filter]").forEach(control => control.setAttribute("aria-pressed", String(control.dataset.filter === "all")));
      renderList("");
    });
    status.textContent = "";
    if (payload.generatedAt) status.dataset.generated = payload.generatedAt;
  } catch (error) {
    status.className = "load-status error";
    status.textContent = error instanceof Error
      ? error.message
      : "No se pudo cargar el mapa.";
    document.getElementById("resultCount").textContent = "Directorio no disponible";
    document.getElementById("storeList").replaceChildren();
    document.getElementById("retryLoad").hidden = false;
    document.getElementById("retryLoad").addEventListener("click", () => window.location.reload(), { once: true });
  } finally {
    document.getElementById("storeList").setAttribute("aria-busy", "false");
  }
}

start();
