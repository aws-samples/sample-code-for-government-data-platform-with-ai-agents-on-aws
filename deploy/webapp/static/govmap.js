// Renders a chart-tool map (points or a council choropleth) into a container with MapLibre. Shared by the chat and share pages.
// Expects window.maplibregl (set by maplibre-loader.mjs) and a global sanitise() from the page. The markup here uses classes
// only, so it renders the same whichever attributes the page's sanitiser allows; .govmap and .govmap-canvas are in layout.html.
var chartCount = 0;
function escHtml(str) {
  var div = document.createElement('div');
  div.appendChild(document.createTextNode(str == null ? '' : String(str)));
  return div.innerHTML;
}
var mapStyleUrl = '/map/style';
// Council boundaries are ONS Open Geography Portal data built on Ordnance Survey data; shown by the attribution control whenever they are on the map
var boundaryAttribution = 'Contains OS data © Crown copyright and database right ' + new Date().getFullYear();

function renderMap(mapData, container) {
  if (!window.maplibregl) { window.addEventListener('maplibre-ready', function() { renderMap(mapData, container); }, { once: true }); return; }
  chartCount++;
  var mapId = 'map-' + chartCount;
  var mapWrapper = document.createElement('div');
  mapWrapper.className = 'govmap';
  mapWrapper.innerHTML = sanitise('<h3 class="govuk-heading-s">' + escHtml(mapData.title || 'Map') + '</h3><div id="' + mapId + '" class="govmap-canvas"></div>');
  container.appendChild(mapWrapper);

  var map = new maplibregl.Map({
    container: mapId,
    style: mapStyleUrl,
    center: [-1.5, 53.5],
    zoom: 5,
    attributionControl: { compact: true },
    validateStyle: false,
  });

    // Reset view button
    var resetDiv = document.createElement('div');
    resetDiv.className = 'maplibregl-ctrl maplibregl-ctrl-group';
    var resetA = document.createElement('button');
    resetA.type = 'button';
    resetA.title = 'Reset map to UK view';
    resetA.setAttribute('aria-label', 'Reset map to UK view');
    resetA.textContent = '⟲';
    resetA.style.cssText = 'font-size:18px;width:29px;height:29px;cursor:pointer;background:#fff;border:none;';
    resetA.addEventListener('click', function() { map.flyTo({ center: [-1.5, 53.5], zoom: 5 }); });
    resetDiv.appendChild(resetA);

    map.addControl({ onAdd: function() { return resetDiv; }, onRemove: function() { resetDiv.remove(); } }, 'top-right');
    map.addControl(new maplibregl.NavigationControl(), 'top-right');

    map.on('load', function() {
      if (mapData.choropleth) {
        fetch('/boundaries').then(function(r) { return r.json(); }).then(function(geojson) {
          if (!geojson || !geojson.features) return;
          var lookup = {};
          mapData.choropleth.forEach(function(d) {
            lookup[d.geography_code] = d;
          });
          var values = mapData.choropleth.map(function(d) { return d.value; });
          var minVal = Math.min.apply(null, values), maxVal = Math.max.apply(null, values);
          var logMin = Math.log(minVal + 1), logMax = Math.log(maxVal + 1), logRange = logMax - logMin || 1;

          geojson.features.forEach(function(f) {
            var d = lookup[f.properties.geography_code];
            if (d) {
              var ratio = (Math.log(d.value + 1) - logMin) / logRange;
              f.properties._fill = 'rgb(' + Math.round(255 * ratio) + ',' + Math.round(255 * (1 - ratio)) + ',50)';
              f.properties._label = '<strong>' + escHtml(d.name) + '</strong><br>' + escHtml(d.label);
              f.properties._matched = 1;
            } else {
              f.properties._fill = 'rgba(0,0,0,0)';
              f.properties._label = '';
              f.properties._matched = 0;
            }
          });

          map.addSource('choropleth', { type: 'geojson', data: geojson, attribution: boundaryAttribution });
          map.addLayer({
            id: 'choropleth-fill', type: 'fill', source: 'choropleth',
            paint: { 'fill-color': ['get', '_fill'], 'fill-opacity': 0.7 }
          });
          map.addLayer({
            id: 'choropleth-line', type: 'line', source: 'choropleth',
            paint: { 'line-color': ['case', ['==', ['get', '_matched'], 1], '#0b0c0c', '#b1b4b6'], 'line-width': ['case', ['==', ['get', '_matched'], 1], 1, 0.5] }
          });

          var popup = new maplibregl.Popup({ closeButton: true, closeOnClick: true });
          map.on('click', 'choropleth-fill', function(e) {
            var html = e.features[0].properties._label;
            if (html) popup.setLngLat(e.lngLat).setHTML(html).addTo(map);
          });
          map.on('mouseenter', 'choropleth-fill', function() { map.getCanvas().style.cursor = 'pointer'; });
          map.on('mouseleave', 'choropleth-fill', function() { map.getCanvas().style.cursor = ''; });

          var bounds = new maplibregl.LngLatBounds();
          geojson.features.forEach(function(f) {
            if (f.properties._matched) {
              var coords = f.geometry.type === 'MultiPolygon' ? f.geometry.coordinates.flat(2) : f.geometry.coordinates.flat(1);
              coords.forEach(function(c) { bounds.extend(c); });
            }
          });
          if (!bounds.isEmpty()) map.fitBounds(bounds, { padding: 20 });
        }).catch(function(err) { console.warn('Choropleth load error:', err); });

      } else {
        var points = mapData.points || [];
        if (points.length > 0) {
          var values = points.map(function(p) { return p.value; });
          var minVal = Math.min.apply(null, values), maxVal = Math.max.apply(null, values), range = maxVal - minVal || 1;

          var geojson = { type: 'FeatureCollection', features: points.map(function(p) {
            var ratio = (p.value - minVal) / range;
            return {
              type: 'Feature',
              geometry: { type: 'Point', coordinates: [p.lng, p.lat] },
              properties: {
                name: p.name,
                label: p.label || String(p.value),
                _fill: 'rgb(' + Math.round(255 * ratio) + ',' + Math.round(255 * (1 - ratio)) + ',50)',
              }
            };
          })};

          map.addSource('points', { type: 'geojson', data: geojson });
          map.addLayer({
            id: 'points-circle', type: 'circle', source: 'points',
            paint: { 'circle-radius': 8, 'circle-color': ['get', '_fill'], 'circle-stroke-color': '#333', 'circle-stroke-width': 1, 'circle-opacity': 0.8 }
          });

          var popup = new maplibregl.Popup({ closeButton: true, closeOnClick: true });
          map.on('click', 'points-circle', function(e) {
            var props = e.features[0].properties;
            popup.setLngLat(e.lngLat).setHTML('<strong>' + escHtml(props.name) + '</strong><br>' + escHtml(props.label)).addTo(map);
          });
          map.on('mouseenter', 'points-circle', function() { map.getCanvas().style.cursor = 'pointer'; });
          map.on('mouseleave', 'points-circle', function() { map.getCanvas().style.cursor = ''; });

          var bounds = new maplibregl.LngLatBounds();
          points.forEach(function(p) { bounds.extend([p.lng, p.lat]); });
          map.fitBounds(bounds, { padding: 40 });
        }
      }
    });
}
