// Exposes the ESM-only maplibre-gl as window.maplibregl for the pages' classic scripts
import * as maplibregl from '/assets/maplibre/maplibre-gl.mjs';

window.maplibregl = maplibregl;
window.dispatchEvent(new Event('maplibre-ready'));
