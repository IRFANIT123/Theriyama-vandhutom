/*
  Navora: DOM-only map presentation. Every backend route point is retained.
  Architectural geometry and routes share one display transform.
*/
const API_BASE = new URLSearchParams(window.location.search).get("api") || "http://127.0.0.1:8000";
const INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape";
const SVG_NS = "http://www.w3.org/2000/svg";

const CORRIDOR_NODE_MATCH_TOLERANCE = 4.0;

const state = {
  floors: [],
  maps: new Map(),
  entrances: [],
  locations: [],
  locationsByFloor: new Map(),
  selectedStart: null,
  selectedDestination: null,
  route: null,
  lastPlan: null,
  blocked: new Set(),
  currentCheckpointIndex: 0,
  selectedFloor: "G",
  floorRouteIndexes: {},
  currentSvg: null,
  originalViewBox: null,
  viewBox: null,
  dragging: false,
  dragStart: null,
  suggestionItems: { start: [], destination: [] },
  globalSuggestionItems: [],
  sourceViewBox: null,
  rotationGroup: null,
  projectionMatrix: null,
  mapMode: "2d",
  mapLoadVersion: 0,
  progressBusy: false,
  routeDisplayStart: "",
  justCompletedIndex: null,
  animateRouteDraw: false,
};

const $ = (id) => document.getElementById(id);
const els = {
  apiPill: $("apiPill"),
  gpsBtn: $("gpsBtn"),
  startSearch: $("startSearch"),
  startSuggestions: $("startSuggestions"),
  startSelection: $("startSelection"),
  clearStartBtn: $("clearStartBtn"),
  destinationSearch: $("destinationSearch"),
  destinationSuggestions: $("destinationSuggestions"),
  clearDestinationBtn: $("clearDestinationBtn"),
  exitChooser: $("exitChooser"),
  exitButtons: $("exitButtons"),
  navigateBtn: $("navigateBtn"),
  formMessage: $("formMessage"),
  routeSummary: $("routeSummary"),
  summaryRouteText: $("summaryRouteText"),
  summaryStartText: $("summaryStartText"),
  summaryTime: $("summaryTime"),
  summaryMode: $("summaryMode"),
  summaryCost: $("summaryCost"),
  summaryFloors: $("summaryFloors"),
  progressPercent: $("progressPercent"),
  progressFill: $("progressFill"),
  currentLandmark: $("currentLandmark"),
  remainingText: $("remainingText"),
  clearRouteBtn: $("clearRouteBtn"),
  mobileRouteDetailsBtn: $("mobileRouteDetailsBtn"),
  mobileRouteDetailsHint: $("mobileRouteDetailsHint"),
  currentFloorTitle: $("currentFloorTitle"),
  currentFloorSubtitle: $("currentFloorSubtitle"),
  floorButtons: $("floorButtons"),
  dockPointCount: $("dockPointCount"),
  dockPointCounter: $("dockPointCounter"),
  floorOverviewButtons: $("floorOverviewButtons"),
  globalSearch: $("globalSearch"),
  globalSuggestions: $("globalSuggestions"),
  themeBtn: $("themeBtn"),
  zoomOutBtn: $("zoomOutBtn"),
  zoomInBtn: $("zoomInBtn"),
  fitBtn: $("fitBtn"),
  mapViewport: $("mapViewport"),
  mapLoading: $("mapLoading"),
  svgHost: $("svgHost"),
  floatingNavControls: $("floatingNavControls"),
  previousCheckpointBtn: $("previousCheckpointBtn"),
  centerMeBtn: $("centerMeBtn"),
  stepBar: $("stepBar"),
  nextStepTitle: $("nextStepTitle"),
  nextStepSubtitle: $("nextStepSubtitle"),
  reportBlockedBtn: $("reportBlockedBtn"),
  currentStepCard: $("currentStepCard"),
  currentStepTitle: $("currentStepTitle"),
  currentStepFloor: $("currentStepFloor"),
  routeInstructionsCard: $("routeInstructionsCard"),
  routeInstructions: $("routeInstructions"),
  instructionCount: $("instructionCount"),
  dockProgressPercent: $("dockProgressPercent"),
  dockProgressFill: $("dockProgressFill"),
  dockRemaining: $("dockRemaining"),
  dockPreviousTitle: $("dockPreviousTitle"),
  dockPreviousMeta: $("dockPreviousMeta"),
  dockCurrentTitle: $("dockCurrentTitle"),
  dockCurrentMeta: $("dockCurrentMeta"),
  dockDestinationTitle: $("dockDestinationTitle"),
  dockDestinationMeta: $("dockDestinationMeta"),
  blockedDialog: $("blockedDialog"),
  applyBlockedBtn: $("applyBlockedBtn"),
  toast: $("toast"),
};

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  const contentType = response.headers.get("content-type") || "";
  return contentType.includes("application/json") ? response.json() : response.text();
}

async function boot() {
  bindEvents();
  try {
    const health = await api("/health");
    setApiStatus(true, "Loading building…");

    const [floors, maps, entrances] = await Promise.all([
      api("/floors"),
      api("/maps"),
      api("/entrances"),
    ]);

    state.floors = floors;
    state.entrances = entrances;
    maps.forEach((m) => state.maps.set(m.floor_id, m));

    const locationLists = await Promise.all(
      floors.map(async (f) => {
        const rows = await api(`/locations?floor_id=${encodeURIComponent(f.floor_id)}&include_non_searchable=true`);
        state.locationsByFloor.set(f.floor_id, rows);
        return rows.filter(location=>Number(location.searchable)===1);
      })
    );
    state.locations = locationLists.flat();
    els.startSearch.disabled = false;
    els.destinationSearch.disabled = false;
    els.globalSearch.disabled = false;
    setApiStatus(true, `Online · ${health.floors} floors`);

    renderExitChoices();
    renderFloorButtons();
    await loadFloorMap("G", true);
  } catch (error) {
    console.error(error);
    setApiStatus(false, "Backend offline");
    showFormError(
      "Navora could not connect to its local API. Start it with: python -m uvicorn backend.main:app --reload"
    );
    // Leave no endless spinner: the map area explains the failure too.
    els.mapLoading.classList.add("error-state");
    els.mapLoading.innerHTML =
      `<span aria-hidden="true" style="font-size:26px">⚠</span>` +
      `<span><strong>No connection to the navigation service</strong></span>` +
      `<span>Floor plans and routes are unavailable until the backend is running.</span>`;
    els.mapLoading.style.display = "grid";
  }
}

function bindEvents() {
  bindSmartSearch("start", els.startSearch, els.startSuggestions);
  bindSmartSearch("destination", els.destinationSearch, els.destinationSuggestions);
  bindGlobalSearch();

  els.clearStartBtn.addEventListener("click", () => clearSelection("start"));
  els.clearDestinationBtn.addEventListener("click", () => clearSelection("destination"));
  els.gpsBtn.addEventListener("click", useGps);
  els.navigateBtn.addEventListener("click", () => planRoute());
  els.clearRouteBtn.addEventListener("click", clearRoute);
  els.mobileRouteDetailsBtn.addEventListener("click", () => {
    const expanded = document.body.classList.toggle("mobile-route-details-open");
    els.mobileRouteDetailsBtn.setAttribute("aria-expanded", String(expanded));
    els.mobileRouteDetailsHint.textContent = expanded ? "Hide full plan" : "Show full plan";
  });
  els.previousCheckpointBtn.addEventListener("click", previousCheckpoint);
  els.centerMeBtn.addEventListener("click", centerCurrentCheckpoint);
  $("confirmNextBtn").addEventListener("click", () => reachCheckpoint(state.currentCheckpointIndex + 1));
  new ResizeObserver(() => requestAnimationFrame(updateOverlayScale)).observe(els.svgHost);
  els.zoomInBtn.addEventListener("click", () => zoomMap(0.82));
  els.zoomOutBtn.addEventListener("click", () => zoomMap(1.22));
  els.fitBtn.addEventListener("click", fitMap);
  document.querySelectorAll("[data-map-mode]").forEach(button => {
    button.addEventListener("click", () => setMapMode(button.dataset.mapMode));
  });
  els.themeBtn.addEventListener("click", () => {
    const enabled=document.body.classList.toggle("evening-mode");
    els.themeBtn.setAttribute("aria-pressed",String(enabled));
  });

  els.mapViewport.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      zoomMap(event.deltaY < 0 ? 0.88 : 1.14, event.clientX, event.clientY);
    },
    { passive: false }
  );
  els.mapViewport.addEventListener("pointerdown", panStart);
  els.mapViewport.addEventListener("pointermove", panMove);
  els.mapViewport.addEventListener("pointerup", panEnd);
  els.mapViewport.addEventListener("pointercancel", panEnd);

  els.reportBlockedBtn.addEventListener("click", openBlockedDialog);
  els.applyBlockedBtn.addEventListener("click", (event) => {
    event.preventDefault();
    rerouteFromCurrentCheckpoint();
  });

  document.querySelectorAll(".avoid-buttons input").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) state.blocked.add(input.value);
      else state.blocked.delete(input.value);
      renderBlockedStatus();
    });
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest(".smart-search")) {
      hideSuggestions("start");
      hideSuggestions("destination");
    }
    if (!event.target.closest(".global-search")) els.globalSuggestions.hidden = true;
  });
}

function setApiStatus(ok, message) {
  els.apiPill.classList.toggle("online", ok);
  els.apiPill.classList.toggle("offline", !ok);
  els.apiPill.querySelector("span:last-child").textContent = message;
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => els.toast.classList.remove("show"), 2400);
}

function showFormError(message) {
  els.formMessage.hidden = false;
  els.formMessage.textContent = message;
}

function clearFormError() {
  els.formMessage.hidden = true;
  els.formMessage.textContent = "";
}

function selectedMode() {
  return document.querySelector('input[name="mode"]:checked')?.value || "lift";
}

function floorName(floorId) {
  return state.floors.find((f) => f.floor_id === floorId)?.name || floorId;
}

function humanize(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (m) => m.toUpperCase());
}

function normalizeText(value) {
  return String(value || "").trim().toLowerCase();
}

function friendlyCode(value) {
  return String(value || "")
    .replace(/ENTRANCE([12])(?:-G)?/gi, "Entrance $1")
    .replace(/LIFT(\d+)(?:-[A-Z0-9]+)?/gi, "Lift $1")
    .replace(/STAIRS?(\d+)(?:-[A-Z0-9-]+)?/gi, "Stair $1")
    .replace(/\b(?:F\d+[_-])?(?:C\d+|F\d+C\d+|circle\d+|ellipse\d+j?)\b/gi, "confirmed point");
}

function navigationFloorName(floorId) {
  if (floorId === "G") return "Ground Floor";
  const match = String(floorId || "").match(/^F(\d+)$/i);
  return match ? `Floor ${match[1]}` : floorName(floorId);
}

function navigationPlaceLabel(value) {
  const cleaned = friendlyCode(value)
    .replace(/^(?:Start|Destination|Near):?\s*/i, "")
    .replace(/Staircase\s*(\d+)/gi, "Stairs $1")
    .trim();
  if (/^(?:G-?\d+|\d+(?:-[A-Z])?)$/i.test(cleaned)) return `Room ${cleaned}`;
  return cleaned;
}

function displayLocation(item) {
  if (item.isEntrance || /entrance/i.test(item.type || "")) return friendlyCode(item.code);
  const name = item.name && item.name !== item.code ? ` · ${item.name}` : "";
  return `${friendlyCode(item.code)}${name}`;
}

const ROOM_SORTER=new Intl.Collator(undefined,{numeric:true,sensitivity:"base"});
const FLOOR_WORDS={
  ground:"G",first:"F1",second:"F2",third:"F3",fourth:"F4",
  fifth:"F5",sixth:"F6",seventh:"F7"
};
function floorSortValue(floorId) {
  if(String(floorId).toUpperCase()==="G")return 0;
  const match=String(floorId).match(/^F(\d+)$/i);
  return match?Number(match[1])+1:99;
}
function floorSearchIntent(query) {
  const q=normalizeText(query).replace(/\s+/g," ");
  if(!q)return null;
  const word=q.match(/^(ground|first|second|third|fourth|fifth|sixth|seventh)(?: floor)?$/);
  if(word)return {floorId:FLOOR_WORDS[word[1]],preferred:false};
  if(/^(?:g|ground floor)$/.test(q))return {floorId:"G",preferred:false};
  const explicit=q.match(/^(?:floor\s*)?([1-7])(?:st|nd|rd|th)(?: floor)?$|^f([1-7])$|^floor\s*([1-7])$/);
  if(explicit)return {floorId:`F${explicit[1]||explicit[2]||explicit[3]}`,preferred:false};
  const digit=q.match(/^([1-7])$/);
  return digit?{floorId:`F${digit[1]}`,preferred:true}:null;
}
function isAllRoomsQuery(query) {
  return /^(?:all|every)(?: available)? (?:room|rooms|location|locations|node|nodes)$|^(?:all|every) rooms?$/i
    .test(String(query||"").trim());
}
function locationSearchResults(query,pool,ordinaryLimit=20) {
  const q=normalizeText(query),floorIntent=floorSearchIntent(q),allRooms=isAllRoomsQuery(q);
  const rooms=pool.filter(item=>!item.isEntrance);
  const floorThenCode=(a,b)=>floorSortValue(a.floor_id)-floorSortValue(b.floor_id)||ROOM_SORTER.compare(a.code,b.code);
  if(allRooms) {
    return rooms.sort(floorThenCode).map(item=>({...item,searchGroup:navigationFloorName(item.floor_id)}));
  }
  if(floorIntent&&!floorIntent.preferred) {
    return rooms.filter(item=>item.floor_id===floorIntent.floorId).sort(floorThenCode)
      .map(item=>({...item,searchGroup:`${navigationFloorName(floorIntent.floorId)} · all available rooms`}));
  }
  if(floorIntent?.preferred) {
    return rooms.sort((a,b)=>{
      const aPreferred=a.floor_id===floorIntent.floorId?0:1,bPreferred=b.floor_id===floorIntent.floorId?0:1;
      return aPreferred-bPreferred||floorThenCode(a,b);
    }).map(item=>({...item,searchGroup:item.floor_id===floorIntent.floorId
      ?`${navigationFloorName(floorIntent.floorId)} · preferred`:`Other available rooms`}));
  }
  const ranked=pool.map(item=>{
    const code=normalizeText(item.code),name=normalizeText(item.name),type=normalizeText(item.type);
    const haystack=normalizeText(`${item.code} ${item.name||""} ${item.type||""} ${item.floor_id||""} ${navigationFloorName(item.floor_id)}`);
    if(!q)return {item,rank:99};
    let rank=haystack.includes(q)?7:99;
    if(type===q)rank=5;
    if(name.startsWith(q))rank=4;
    if(name===q)rank=3;
    if(code.includes(q))rank=2;
    if(code.startsWith(q))rank=1;
    if(code===q)rank=0;
    return {item,rank};
  }).filter(entry=>entry.rank<99).sort((a,b)=>a.rank-b.rank||floorThenCode(a.item,b.item));
  return ranked.slice(0,ordinaryLimit).map(entry=>entry.item);
}
function suggestionRows(results,attributes) {
  let previousGroup="";
  return results.map((item,index)=>{
    const group=item.searchGroup||"";
    const heading=group&&group!==previousGroup
      ?`<div class="suggestion-group">${escapeHtml(group)}</div>`:"";
    previousGroup=group;
    return `${heading}<button class="suggestion-item" type="button" ${attributes(item,index)}>
      <span class="suggestion-icon">${escapeHtml(locationIcon(item.type))}</span>
      <span class="suggestion-copy"><strong>${escapeHtml(displayLocation(item))}</strong>
      <span>${escapeHtml(navigationFloorName(item.floor_id))} · ${escapeHtml(humanize(item.type||"location"))}</span></span></button>`;
  }).join("");
}

function renderBlockedStatus() {
  const selected = [...state.blocked].map(friendlyCode);
  $("blockedStatus").hidden = !selected.length;
  const replacement = (state.route?.instructions || [])
    .map(item => item.text?.match(/(?:Proceed to|Take the)\s+((?:Lift|Stair(?:case)?s?)\s*\d+)/i)?.[1])
    .filter(Boolean)
    .map(item => item.replace(/Staircase/i, "Stairs"))
    .find(item => !selected.some(blocked => normalizeText(blocked) === normalizeText(item)));
  if (selected.length === 1) {
    $("blockedStatus").textContent = `${selected[0]} unavailable. ${replacement ? `Use ${replacement} instead.` : "It will be avoided."}`;
  } else if (selected.length) {
    $("blockedStatus").textContent = `Avoiding ${selected.join(", ")}.${replacement ? ` Use ${replacement} instead.` : ""}`;
  } else {
    $("blockedStatus").textContent = "";
  }
  document.querySelectorAll(".avoid-buttons input").forEach(input => { input.checked=state.blocked.has(input.value); });
  // The planning panel is hidden during navigation, so mirror the notice into
  // the live route summary — otherwise an active avoidance becomes invisible.
  const mirror = $("routeBlockedStatus");
  if (mirror) {
    mirror.hidden = $("blockedStatus").hidden;
    mirror.textContent = $("blockedStatus").textContent;
  }
  syncBlockedConnectorStyles();
}

function syncBlockedConnectorStyles() {
  state.currentSvg?.querySelectorAll("[data-connector-code]").forEach(element => {
    element.classList.toggle(
      "cn-connector-unavailable",
      state.blocked.has(element.dataset.connectorCode)
    );
  });
}

function tagConnector(element, code) {
  if (!element) return;
  element.dataset.connectorCode = code;
  element.classList.toggle("cn-connector-unavailable", state.blocked.has(code));
}

function locationIcon(type) {
  const t = normalizeText(type);
  if (/toilet|bathroom|washroom|wc/.test(t)) return "🚻";
  if (/lab/.test(t)) return "⚗";
  if (/faculty|office/.test(t)) return "▣";
  if (/entrance|exit/.test(t)) return "↗";
  return "□";
}

function bindSmartSearch(kind, input, suggestions) {
  input.addEventListener("keydown", event => {
    if (event.key === "Escape") hideSuggestions(kind);
    if (event.key === "ArrowDown" && !suggestions.hidden) {
      event.preventDefault();
      suggestions.querySelector("button")?.focus();
    }
    if (event.key === "Enter" && !suggestions.hidden && state.suggestionItems[kind].length === 1) {
      event.preventDefault();
      chooseLocation(kind, state.suggestionItems[kind][0]);
    }
  });
  input.addEventListener("input", () => {
    clearFormError();
    if (kind === "start") {
      state.selectedStart = null;
      els.startSelection.hidden = true;
    }
    else state.selectedDestination = null;

    const query = input.value.trim();
    if (kind === "destination") {
      const wantsExit = /(^|\s)exit(\s|$)/i.test(query) || /^leave\b/i.test(query);
      els.exitChooser.hidden = !wantsExit;
      if (wantsExit) {
        hideSuggestions("destination");
        return;
      }
    }
    renderSuggestions(kind, query, suggestions);
  });

  input.addEventListener("focus", () => {
    const query = input.value.trim();
    if (kind === "destination" && /(^|\s)exit(\s|$)/i.test(query)) {
      els.exitChooser.hidden = false;
      return;
    }
    renderSuggestions(kind, query, suggestions);
  });
}

function bindGlobalSearch() {
  const input=els.globalSearch,container=els.globalSuggestions;
  input.addEventListener("input",()=>renderGlobalSuggestions(input.value));
  input.addEventListener("focus",()=>renderGlobalSuggestions(input.value));
  input.addEventListener("keydown",event=>{
    if(event.key==="Escape")container.hidden=true;
    if(event.key==="ArrowDown"&&!container.hidden){event.preventDefault();container.querySelector("button")?.focus();}
    if(event.key==="Enter"&&!container.hidden&&state.globalSuggestionItems.length===1){
      event.preventDefault();chooseGlobalSearchResult(state.globalSuggestionItems[0]);
    }
  });
}

function renderGlobalSuggestions(query) {
  const q=normalizeText(query),container=els.globalSuggestions;
  if(!q){container.hidden=true;state.globalSuggestionItems=[];return;}
  let results;
  if(/(^|\s)exit(\s|$)/i.test(q)||/^leave\b/i.test(q)) {
    results=[{kind:"exit",exitMode:"nearest",floor_id:"G",code:"EXIT",name:"Nearest Exit",type:"exit"},
      ...state.entrances.map(entrance=>({kind:"exit",exitMode:"specific",floor_id:"G",code:entrance.original_node_id,
        name:`Exit via ${entrance.label}`,type:"exit"}))];
  } else {
    results=locationSearchResults(q,[...state.locations]).map(item=>({...item,kind:"location"}));
  }
  state.globalSuggestionItems=results;
  if(!results.length){container.innerHTML='<div class="suggestion-empty">No matching room or facility.</div>';container.hidden=false;return;}
  container.innerHTML=results.some(item=>item.kind==="exit")
    ?results.map((item,index)=>`<button class="suggestion-item" type="button" data-global-index="${index}">
      <span class="suggestion-icon">${escapeHtml(locationIcon(item.type))}</span>
      <span class="suggestion-copy"><strong>${escapeHtml(item.name)}</strong>
      <span>${escapeHtml(navigationFloorName(item.floor_id||"G"))} · ${escapeHtml(humanize(item.type||"location"))}</span></span></button>`).join("")
    :suggestionRows(results,(_item,index)=>`data-global-index="${index}"`);
  container.hidden=false;
  container.querySelectorAll("[data-global-index]").forEach(button=>button.addEventListener("click",()=>{
    chooseGlobalSearchResult(results[Number(button.dataset.globalIndex)]);
  }));
}

function chooseGlobalSearchResult(item) {
  if(!item)return;
  if(item.kind==="exit") {
    state.selectedDestination={kind:"exit",exitMode:item.exitMode,floor_id:"G",code:item.code,name:item.name,type:"exit"};
    els.destinationSearch.value=item.name;
    els.exitChooser.hidden=true;
    els.globalSearch.value=item.name;
    showToast(`${item.name} selected`);
  } else {
    chooseLocation("destination",item);
    els.globalSearch.value=displayLocation(item);
  }
  els.globalSuggestions.hidden=true;
}

function renderSuggestions(kind, query, container) {
  const q = normalizeText(query);
  let pool = [...state.locations];

  if (kind === "start") {
    const entranceItems = state.entrances.map((e) => ({
      floor_id: "G",
      code: e.original_node_id,
      name: `${e.label} · Entrance`,
      type: "entrance",
      isEntrance: true,
    }));
    pool = [...entranceItems, ...pool];
  }

  let results=!q
    ?(kind==="start"?pool.filter(item=>item.floor_id==="G").slice(0,12):[])
    :locationSearchResults(q,pool);
  state.suggestionItems[kind] = results;

  if (!results.length) {
    if (!q) {
      container.hidden = true;
      return;
    }
    container.innerHTML = `<div class="suggestion-empty">No matching location found.</div>`;
    container.hidden = false;
    return;
  }

  container.innerHTML=suggestionRows(results,(_item,index)=>`data-kind="${kind}" data-index="${index}"`);
  container.hidden = false;

  container.querySelectorAll(".suggestion-item").forEach((button) => {
    button.addEventListener("click", () => {
      const item = state.suggestionItems[kind][Number(button.dataset.index)];
      chooseLocation(kind, item);
    });
  });
}

function chooseLocation(kind, item) {
  if (!item) return;
  const selection = {
    kind: "location",
    floor_id: item.floor_id,
    code: item.code,
    name: item.name || item.code,
    type: item.type || "location",
  };

  if (kind === "start") {
    state.selectedStart = selection;
    els.startSearch.value = `${friendlyCode(item.code)} · ${floorName(item.floor_id)}`;
    els.startSelection.hidden = false;
    els.startSelection.textContent = `Start confirmed: ${friendlyCode(item.code)} on ${floorName(item.floor_id)}`;
    hideSuggestions("start");
  } else {
    state.selectedDestination = selection;
    els.destinationSearch.value = `${friendlyCode(item.code)} · ${floorName(item.floor_id)}`;
    els.globalSearch.value = displayLocation(item);
    els.exitChooser.hidden = true;
    hideSuggestions("destination");
  }
}

function clearSelection(kind) {
  if (kind === "start") {
    state.selectedStart = null;
    els.startSearch.value = "";
    els.startSelection.hidden = true;
    els.startSearch.focus();
  } else {
    state.selectedDestination = null;
    els.destinationSearch.value = "";
    els.globalSearch.value = "";
    els.exitChooser.hidden = true;
    renderExitChoices();
    els.destinationSearch.focus();
  }
}

function hideSuggestions(kind) {
  const el = kind === "start" ? els.startSuggestions : els.destinationSuggestions;
  el.hidden = true;
}

function renderExitChoices() {
  const options = [
    {
      mode: "nearest",
      code: "EXIT",
      label: "Nearest available exit",
      description: "Navora chooses the best exit for your current route.",
    },
    ...state.entrances.map((e) => ({
      mode: "specific",
      code: e.original_node_id,
      label: `Exit via ${e.label}`,
      description: "Ground Floor · building entrance and exit",
    })),
  ];

  els.exitButtons.innerHTML = options
    .map(
      (option, index) => `
        <button class="exit-choice-btn" type="button" data-exit-index="${index}">
          <span>
            <strong>${escapeHtml(option.label)}</strong>
            <small>${escapeHtml(option.description)}</small>
          </span>
          <span class="exit-arrow">→</span>
        </button>`
    )
    .join("");

  els.exitButtons.querySelectorAll(".exit-choice-btn").forEach((button) => {
    button.addEventListener("click", () => {
      const option = options[Number(button.dataset.exitIndex)];
      state.selectedDestination = {
        kind: "exit",
        exitMode: option.mode,
        floor_id: "G",
        code: option.code,
        name: option.label,
        type: "exit",
      };
      els.destinationSearch.value = option.label;
      els.globalSearch.value = option.label;
      els.exitChooser.hidden = true;
      els.exitButtons.querySelectorAll(".exit-choice-btn").forEach((b) => b.classList.remove("selected"));
      button.classList.add("selected");
      showToast(`${option.label} selected`);
    });
  });
}

async function useGps() {
  clearFormError();
  if (!navigator.geolocation) {
    showFormError("This browser does not provide geolocation. Choose a start location manually.");
    return;
  }

  els.gpsBtn.disabled = true;
  els.gpsBtn.querySelector("span:last-child").textContent = "Locating entrance…";

  navigator.geolocation.getCurrentPosition(
    async (position) => {
      try {
        const { latitude, longitude, accuracy } = position.coords;
        const result = await api(
          `/nearest-entrance?latitude=${encodeURIComponent(latitude)}&longitude=${encodeURIComponent(longitude)}&accuracy_m=${encodeURIComponent(accuracy || 0)}`
        );
        const entrance = result.nearest_entrance;
        state.selectedStart = {
          kind: "location",
          floor_id: "G",
          code: entrance.node_id,
          name: entrance.label,
          type: "entrance",
        };
        els.startSearch.value = `${entrance.label} · GPS detected`;
        els.startSelection.hidden = false;
        els.startSelection.textContent = `${result.message} Distance: about ${Number(entrance.distance_m || 0).toFixed(1)} m.`;
        showToast(`Nearest entrance: ${entrance.label}`);
      } catch (error) {
        showFormError(error.message);
      } finally {
        els.gpsBtn.disabled = false;
        els.gpsBtn.querySelector("span:last-child").textContent = "Locate me";
      }
    },
    (error) => {
      els.gpsBtn.disabled = false;
      els.gpsBtn.querySelector("span:last-child").textContent = "Locate me";
      showFormError(
        error.code === 1
          ? "Location permission was denied. Choose your entrance/start point manually."
          : "GPS position could not be read. Try again outside near the building."
      );
    },
    { enableHighAccuracy: true, timeout: 12000, maximumAge: 5000 }
  );
}

function collectBlocked(extra = []) {
  const result = new Set(state.blocked);
  document.querySelectorAll(".avoid-buttons input:checked").forEach((input) => result.add(input.value));
  extra.forEach((item) => item && result.add(item));
  result.delete("STRING");
  return [...result];
}

function appendBlocked(params, blocked) {
  blocked.forEach((item) => params.append("blocked", item));
}

async function planRoute(overrides = {}) {
  clearFormError();

  const start = overrides.start || state.selectedStart;
  const destination = overrides.destination || state.selectedDestination;
  const mode = overrides.mode || selectedMode();
  const blocked = collectBlocked(overrides.blocked || []);

  if (!start) {
    showFormError("Choose your current room/start point, or use outdoor GPS.");
    return;
  }
  if (!destination) {
    showFormError('Choose a destination. You can also type "exit" to choose an exit.');
    return;
  }

  els.navigateBtn.disabled = true;
  els.navigateBtn.querySelector("span:first-child").textContent = "Finding route…";

  try {
    const params = new URLSearchParams({
      start_floor: start.floor_id,
      start: start.code,
      mode,
    });
    appendBlocked(params, blocked);

    let route;
    if (destination.kind === "exit" && destination.exitMode === "nearest") {
      route = await api(`/route-to-exit?${params.toString()}`);
    } else {
      params.set("destination_floor", destination.floor_id);
      params.set("destination", destination.code);
      route = await api(`/route?${params.toString()}`);
    }

    state.route = route;
    state.justCompletedIndex = null;
    state.animateRouteDraw = true;
    document.body?.classList?.remove("route-arrived");
    document.body?.classList?.add("route-active");
    document.body?.classList?.remove("mobile-route-details-open");
    els.mobileRouteDetailsBtn.setAttribute("aria-expanded", "false");
    els.mobileRouteDetailsHint.textContent = "Show full plan";
    state.routeDisplayStart = start.type === "checkpoint" ? friendlyCode(start.name) : friendlyCode(start.code);
    state.blocked = new Set((route.blocked || []).filter((x) => x && x !== "STRING"));
    state.currentCheckpointIndex = 0;
    renderBlockedStatus();
    const displayTarget = checkpointDisplayTarget();
    state.selectedFloor = displayTarget?.floor_id || route.floors[0];
    state.lastPlan = {
      destination: { ...destination },
      mode,
    };

    buildGlobalPathIndexes();
    renderRouteSummary();
    renderInstructions();
    renderFloorButtons();
    updateProgressUi();
    els.routeSummary.hidden = false;
    els.floatingNavControls.hidden = false;
    els.stepBar.hidden = false;
    els.currentStepCard.hidden = false;
    els.routeInstructionsCard.hidden = false;

    await loadFloorMap(state.selectedFloor, true);
    focusRoutePreview();
    if (window.matchMedia("(max-width:760px)").matches) {
      els.mapViewport.scrollIntoView({
        block: "center",
        behavior: window.matchMedia("(prefers-reduced-motion:reduce)").matches ? "auto" : "smooth",
      });
    }
    showToast("Route ready");
  } catch (error) {
    console.error(error);
    showFormError(error.message);
  } finally {
    els.navigateBtn.disabled = false;
    els.navigateBtn.querySelector("span:first-child").textContent = "Get Route";
  }
}

function renderRouteSummary() {
  const r = state.route;
  if (!r) return;
  const destinationLabel = r.destination === "EXIT" && r.chosen_exit ? r.chosen_exit.label : r.destination;
  const floorCount = new Set(r.floors || []).size;
  const estimatedMinutes = Math.max(
    1,
    Math.ceil(Number(r.total_cost || 0) / 65 + Math.max(0, floorCount - 1) * 0.55)
  );
  els.summaryRouteText.textContent = `To ${navigationPlaceLabel(destinationLabel)}`;
  els.summaryStartText.textContent = navigationPlaceLabel(state.routeDisplayStart || r.start);
  els.summaryTime.textContent = `${estimatedMinutes} min`;
  els.summaryMode.textContent = floorCount > 1 ? humanize(r.mode) : "Walking";
  els.summaryCost.textContent = `${Math.round(Number(r.total_cost || 0))} m`;
  els.summaryFloors.textContent = `${floorCount} floor${floorCount === 1 ? "" : "s"}`;
  els.dockDestinationTitle.textContent = navigationPlaceLabel(destinationLabel);
  els.dockDestinationMeta.textContent = `${Math.round(Number(r.total_cost || 0))} m route`;
}

function buildGeometryDirections() {
  const output = [];
  const route = state.route;
  if (!route) return output;

  for (const floor of route.floors || []) {
    const points = route.floor_routes?.[floor] || [];
    if (points.length < 3) continue;

    for (let i = 1; i < points.length - 1; i++) {
      const a = points[i - 1], b = points[i], c = points[i + 1];
      const v1x = b.x - a.x, v1y = b.y - a.y;
      const v2x = c.x - b.x, v2y = c.y - b.y;
      const l1 = Math.hypot(v1x, v1y), l2 = Math.hypot(v2x, v2y);
      if (l1 < 0.001 || l2 < 0.001) continue;

      const dot = (v1x * v2x + v1y * v2y) / (l1 * l2);
      const angle = Math.acos(Math.max(-1, Math.min(1, dot))) * 180 / Math.PI;
      if (angle < 38) continue;

      // SVG coordinates have +Y downward. Positive cross therefore represents
      // a clockwise/right turn on the displayed floor. A 90° rotation preserves
      // handedness, so the same left/right remains valid after display rotation.
      const cross = v1x * v2y - v1y * v2x;
      const direction = cross > 0 ? "right" : "left";
      const pathIndex = state.floorRouteIndexes?.[floor]?.[i]?.globalIndex;
      const nearby = (route.checkpoints || []).find(
        (cp) => cp.floor_id === floor && Math.abs((cp.path_index ?? -999) - pathIndex) <= 2
      );
      const context = nearby && !/^Route checkpoint$/i.test(nearby.label || "")
        ? ` near ${navigationPlaceLabel(nearby.label)}`
        : "";
      output.push({
        type: "turn",
        floor,
        text: `Turn ${direction}${context} and continue along the corridor`,
        pathIndex: Number.isFinite(pathIndex) ? pathIndex : i,
      });
    }
  }
  return output;
}

function renderInstructions() {
  const route = state.route;
  if (!route) return;
  const backend = route.instructions || [];
  const floors = [...new Set(route.floors || [])];
  const startFloor = floors[0] || "";
  const destinationFloor = floors.at(-1) || startFloor;
  const rawDestination = route.destination === "EXIT" && route.chosen_exit
    ? route.chosen_exit.label
    : route.destination;
  const destination = navigationPlaceLabel(rawDestination);
  const connectorInstruction = backend.find(item => item.type === "connector");
  const connectorMatch = connectorInstruction?.text?.match(/(?:Proceed to|Walk to)\s+(.+)/i);
  const connector = connectorMatch
    ? navigationPlaceLabel(connectorMatch[1])
    : null;
  const vertical = backend.find(item => item.type === "lift" || item.type === "stairs");
  const items = [];

  if (connector) {
    const connectorCheckpoint = (route.checkpoints || []).find(cp =>
      normalizeText(cp.label).includes(normalizeText(connector).replace("stairs", "stair"))
    );
    const startRemaining = Number(route.checkpoints?.[0]?.remaining_distance_m || route.total_cost || 0);
    const connectorRemaining = Number(connectorCheckpoint?.remaining_distance_m || 0);
    const walkDistance = Math.max(1, Math.round(startRemaining - connectorRemaining));
    items.push({
      text: `Walk to ${connector}`,
      detail: `About ${walkDistance} m · ${navigationFloorName(startFloor)}`,
    });
  } else {
    items.push({
      text: `Follow the highlighted route`,
      detail: `From ${navigationPlaceLabel(state.routeDisplayStart || route.start)}`,
    });
  }

  if (vertical && floors.length > 1) {
    const mode = vertical.type === "stairs" ? "stairs" : "lift";
    items.push({
      text: `Take ${mode} → ${navigationFloorName(destinationFloor)}`,
      detail: connector ? `Use ${connector}` : "Follow the floor signs",
    });
  } else {
    buildGeometryDirections().slice(0, 2).forEach(turn => {
      items.push({
        text: navigationPlaceLabel(turn.text),
        detail: navigationFloorName(turn.floor),
      });
    });
  }

  items.push({
    text: `${destination} is ahead`,
    detail: navigationFloorName(destinationFloor),
  });

  els.instructionCount.textContent = `${items.length} step${items.length === 1 ? "" : "s"}`;
  els.routeInstructions.innerHTML = items
    .map((item, index) => `
      <div class="instruction-item">
        <span class="instruction-number">${index + 1}</span>
        <span class="instruction-copy">
          <strong>${escapeHtml(item.text)}</strong>
          <span>${escapeHtml(item.detail || "")}</span>
        </span>
      </div>`)
    .join("");
}

function buildGlobalPathIndexes() {
  state.floorRouteIndexes = {};
  if (!state.route) return;
  const raw = state.route.raw_node_path || [];
  let cursor = 0;

  for (const floor of state.route.floors || []) {
    const points = state.route.floor_routes?.[floor] || [];
    state.floorRouteIndexes[floor] = [];
    for (const point of points) {
      let found = -1;
      for (let i = cursor; i < raw.length; i++) {
        if (raw[i] === point.node_id) {
          found = i;
          cursor = i + 1;
          break;
        }
      }
      state.floorRouteIndexes[floor].push({ ...point, globalIndex: found });
    }
  }
}

function renderFloorButtons() {
  const allFloors = state.floors.map((f) => f.floor_id);
  const routeFloors = [...new Set(state.route?.floors || [])];
  if (els.floorButtons) els.floorButtons.innerHTML = allFloors
    .map(
      (floor) => `
        <button class="floor-button ${routeFloors.includes(floor) ? "on-route" : ""} ${floor === state.selectedFloor ? "active" : ""}" type="button" data-floor="${escapeHtml(floor)}" aria-pressed="${floor === state.selectedFloor}" aria-label="${escapeHtml(floorName(floor))}">
          <strong>${escapeHtml(floor)}</strong>
          <span>${escapeHtml(shortFloorName(floorName(floor)))}</span>
        </button>`
    )
    .join("");
  els.floorOverviewButtons.innerHTML=[...allFloors].reverse().map(floor=>`
    <button class="floor-overview-button ${routeFloors.includes(floor)?"on-route":""} ${floor===state.selectedFloor?"active":""}"
      type="button" data-floor="${escapeHtml(floor)}" aria-pressed="${floor===state.selectedFloor}" aria-label="Show ${escapeHtml(floorName(floor))}">${escapeHtml(floor)}</button>`).join("");

  document.querySelectorAll("#floorButtons [data-floor],#floorOverviewButtons [data-floor]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.selectedFloor = button.dataset.floor;
      renderFloorButtons();
      await loadFloorMap(state.selectedFloor, true);
    });
  });
}

function shortFloorName(name) {
  return String(name).replace(/ floor/i, "");
}

function updateProgressUi() {
  if (!state.route?.checkpoints?.length) return;
  const cp = state.route.checkpoints[state.currentCheckpointIndex];
  const next = state.route.checkpoints[state.currentCheckpointIndex + 1];
  const progress = Number(cp.progress_percent || 0);
  const segmentDistance = next
    ? Math.max(1, Math.round(Number(cp.remaining_distance_m || 0) - Number(next.remaining_distance_m || 0)))
    : 0;

  const total = state.route.checkpoints.length;
  const pointNumber = cp.checkpoint;
  const arrived = !next;

  els.progressPercent.textContent = `${progress}%`;
  els.progressFill.style.width = `${Math.max(0, Math.min(100, progress))}%`;
  els.dockProgressPercent.textContent = `${progress}%`;
  els.dockProgressFill.style.width = `${Math.max(0, Math.min(100, progress))}%`;

  // Explicit "where am I in the sequence" readout, taken straight from the
  // backend checkpoint numbering.
  if (els.dockPointCount) {
    els.dockPointCount.textContent = arrived ? "Arrived" : "Route progress";
  }
  if (els.dockPointCounter) {
    els.dockPointCounter.textContent = arrived
      ? `All ${total} points complete`
      : `Point ${pointNumber} of ${total} · ${total - pointNumber} to go`;
  }
  document.body.classList.toggle("route-arrived", arrived);
  els.reportBlockedBtn.disabled = arrived;
  els.currentLandmark.textContent = navigationPlaceLabel(cp.label);
  els.remainingText.textContent = `${cp.remaining_distance_m} m remaining`;
  els.dockRemaining.textContent = `${cp.remaining_distance_m} m remaining`;
  els.dockCurrentTitle.textContent = navigationPlaceLabel(cp.label);
  els.dockCurrentMeta.textContent = next
    ? `Next: Point ${next.checkpoint}${next.is_turn ? ` · turn ${next.turn_direction}` : ""}`
    : "Destination reached";
  const previous=state.route.checkpoints[state.currentCheckpointIndex-1];
  els.dockPreviousTitle.textContent = previous ? navigationPlaceLabel(previous.label) : "Route start";
  els.dockPreviousMeta.textContent = previous ? navigationFloorName(previous.floor_id) : "Beginning";
  els.previousCheckpointBtn.disabled = state.currentCheckpointIndex <= 0 || state.progressBusy;
  $("confirmNextBtn").disabled = !next || state.progressBusy;
  $("confirmNextBtn").textContent = next ? "I'm here →" : "Arrived";
  $("confirmNextBtn").setAttribute(
    "aria-label",
    next ? `Confirm route point ${next.checkpoint}: ${navigationPlaceLabel(next.label)}` : "Destination reached"
  );
  $("journeyProgress").setAttribute("aria-valuenow", Math.max(0, Math.min(100, progress)));

  els.currentStepTitle.textContent = navigationPlaceLabel(cp.label);
  els.currentStepFloor.textContent = navigationFloorName(cp.floor_id);

  if (next) {
    const isFloorChange = next.floor_id !== cp.floor_id;
    const isDestination = state.currentCheckpointIndex + 1 === state.route.checkpoints.length - 1;
    const nextLabel = navigationPlaceLabel(next.label);
    if (isFloorChange) {
      els.nextStepTitle.textContent = `Take ${connectorWord(cp, next)} → ${navigationFloorName(next.floor_id)}`;
      els.nextStepSubtitle.textContent = `Point ${next.checkpoint} · confirm after exiting on ${navigationFloorName(next.floor_id)}`;
    } else if (isDestination) {
      els.nextStepTitle.textContent = `Point ${next.checkpoint} · ${nextLabel}`;
      els.nextStepSubtitle.textContent = `Destination · about ${segmentDistance} m`;
    } else if (/lift|stair/i.test(next.label || "")) {
      els.nextStepTitle.textContent = `Point ${next.checkpoint} · walk to ${nextLabel}`;
      els.nextStepSubtitle.textContent = `About ${segmentDistance} m · ${navigationFloorName(next.floor_id)}`;
    } else if (next.is_turn) {
      els.nextStepTitle.textContent = `Point ${next.checkpoint} · turn ${next.turn_direction}`;
      els.nextStepSubtitle.textContent = `About ${segmentDistance} m · ${nextLabel}`;
    } else {
      els.nextStepTitle.textContent = `Point ${next.checkpoint} · continue straight`;
      els.nextStepSubtitle.textContent = `About ${segmentDistance} m · follow the numbered route point`;
    }
  } else {
    els.nextStepTitle.textContent = "Destination reached";
    els.nextStepSubtitle.textContent = "Navigation complete";
  }
}

function checkpointDisplayTarget(index = state.currentCheckpointIndex) {
  const cp = state.route?.checkpoints?.[index];
  const next = state.route?.checkpoints?.[index + 1];
  // A confirmed departure displays the unconfirmed arrival on the next floor.
  // Use the same rule when planning, advancing, or undoing a confirmation.
  return next?.floor_id && next.floor_id !== cp?.floor_id ? next : cp;
}

async function reachCheckpoint(index) {
  if (state.progressBusy || !state.route?.checkpoints?.[index] || index <= state.currentCheckpointIndex) return;
  if (index > state.currentCheckpointIndex + 1) {
    showToast("Confirm checkpoints in order — tap the next dot first");
    return;
  }

  state.progressBusy = true;
  state.currentCheckpointIndex = index;
  state.justCompletedIndex = index;
  state.animateRouteDraw = true;
  const cp = state.route.checkpoints[index];
  const next = state.route.checkpoints[index + 1];

  updateProgressUi();

  // Cross-floor hand-off:
  // Once the user confirms the connector checkpoint (lift/stairs) on the
  // current floor, immediately display the next routed floor. Previously the
  // app stayed on the old floor, while the next tappable checkpoint existed
  // only on the new floor, which trapped navigation at the connector.
  const displayTarget = checkpointDisplayTarget();
  const hasFloorTransition = displayTarget === next;
  const displayFloor = displayTarget.floor_id;

  state.selectedFloor = displayFloor;
  renderFloorButtons();
  if (state.currentSvg && displayFloor === state.currentSvg.dataset.floor) drawRouteOverlay();
  else await loadFloorMap(displayFloor, false);

  if (hasFloorTransition) {
    // Center on the next floor's arrival checkpoint so the user sees where
    // to continue after exiting the lift/stairs. Progress still remains at
    // the last manually confirmed checkpoint until that next dot is tapped.
    focusRemainingRoute(next);
    showToast(`${humanize(connectorWord(cp, next))} to ${floorName(next.floor_id)} — map switched`);
  } else {
    focusRemainingRoute(cp);
    showToast(
      index === state.route.checkpoints.length - 1
        ? "Destination reached"
        : `Progress updated · ${cp.progress_percent}%`
    );
  }
  state.progressBusy = false;
  updateProgressUi();
  // The flash is one-shot: clear it so later redraws (pan, zoom, floor
  // switch) do not replay it.
  setTimeout(() => {
    if (state.justCompletedIndex === index) state.justCompletedIndex = null;
  }, 700);
}

function connectorWord(cp, next) {
  const text = `${cp?.label || ""} ${next?.label || ""}`.toLowerCase();
  if (text.includes("stair")) return "stairs";
  if (text.includes("lift") || text.includes("elevator")) return "lift";
  return "connector";
}

async function previousCheckpoint() {
  if (state.progressBusy || !state.route || state.currentCheckpointIndex <= 0) return;
  state.progressBusy = true;
  state.currentCheckpointIndex -= 1;
  const displayTarget = checkpointDisplayTarget();
  state.selectedFloor = displayTarget.floor_id;
  renderFloorButtons();
  updateProgressUi();
  if (state.currentSvg && displayTarget.floor_id === state.currentSvg.dataset.floor) drawRouteOverlay();
  else await loadFloorMap(displayTarget.floor_id, false);
  focusRemainingRoute(displayTarget);
  state.progressBusy = false;
  updateProgressUi();
  showToast("Moved back to the previous checkpoint");
}

function centerCurrentCheckpoint() {
  const cp = state.route?.checkpoints?.[state.currentCheckpointIndex];
  if (cp && cp.floor_id === state.selectedFloor) centerOnCheckpoint(cp);
  else if (cp) {
    state.selectedFloor = cp.floor_id;
    renderFloorButtons();
    loadFloorMap(cp.floor_id, false).then(() => centerOnCheckpoint(cp));
  }
}

function clearRoute() {
  state.route = null;
  state.lastPlan = null;
  state.currentCheckpointIndex = 0;
  state.justCompletedIndex = null;
  state.animateRouteDraw = false;
  document.body.classList.remove("route-arrived");
  state.blocked.clear();
  renderBlockedStatus();
  state.floorRouteIndexes = {};
  document.body?.classList?.remove("route-active");
  document.body?.classList?.remove("mobile-route-details-open");
  els.mobileRouteDetailsBtn.setAttribute("aria-expanded", "false");
  els.mobileRouteDetailsHint.textContent = "Show full plan";
  els.routeSummary.hidden = true;
  els.floatingNavControls.hidden = true;
  els.stepBar.hidden = true;
  els.currentStepCard.hidden = true;
  els.routeInstructionsCard.hidden = true;
  if (state.currentSvg) state.currentSvg.querySelector("#campusnav-route-overlay")?.remove();
  document.querySelectorAll(".avoid-buttons input").forEach((input) => (input.checked = false));
  renderFloorButtons();
  showToast("Route cleared");
}

async function loadFloorMap(floorId, fitAfter = true) {
  const loadVersion = ++state.mapLoadVersion;
  state.selectedFloor = floorId;
  state.currentSvg = null;
  state.sourceViewBox = null;
  state.rotationGroup = null;
  state.projectionMatrix = null;
  renderFloorButtons();
  els.currentFloorTitle.textContent = `E Block · ${floorId}`;
  els.currentFloorSubtitle.textContent = floorName(floorId);
  els.mapLoading.innerHTML = `<div class="spinner"></div><span>Loading ${escapeHtml(floorName(floorId))}…</span>`;
  els.mapLoading.style.display = "grid";
  els.svgHost.innerHTML = "";

  try {
    const map = state.maps.get(floorId);
    if (!map?.url) throw new Error(`No SVG map is registered for ${floorId}.`);
    const svgText = await api(map.url);
    if (loadVersion !== state.mapLoadVersion) return;
    const doc = new DOMParser().parseFromString(svgText, "image/svg+xml");
    if (doc.querySelector("parsererror")) throw new Error(`${floorId} SVG could not be parsed.`);

    const svg = document.importNode(doc.documentElement, true);
    svg.removeAttribute("width");
    svg.removeAttribute("height");
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    svg.setAttribute("aria-label", `${floorName(floorId)} map`);
    const mapTitle = svg.querySelector("title");
    if (mapTitle) mapTitle.textContent = `${floorName(floorId)} · E Block`;
    els.svgHost.replaceChildren(svg);
    state.currentSvg = svg;
    svg.dataset.floor = floorId;

    // Decorate in the SVG's native coordinate system first. Then rotate the
    // complete rendered map in one shared group. Route coordinates remain in
    // their original backend/SVG coordinate system and therefore stay aligned.
    decorateBlueprint(svg, floorId);
    const projectedViewBox = enableClockwiseMapRotation(svg);
    raiseMapLabels(svg);
    state.originalViewBox = mapContentViewBox(svg, projectedViewBox);
    state.viewBox = { ...state.originalViewBox };
    applyViewBox();

    drawRouteOverlay();
    applyMapMode();
    if (fitAfter) fitMap();
    els.mapLoading.style.display = "none";
  } catch (error) {
    if (loadVersion !== state.mapLoadVersion) return;
    console.error(error);
    els.mapLoading.innerHTML =
      `<span aria-hidden="true" style="font-size:22px">⚠</span>` +
      `<span><strong>This floor plan could not be loaded.</strong></span>` +
      `<span>${escapeHtml(error.message)}</span>`;
    els.mapLoading.classList.add("error-state");
    els.mapLoading.style.display = "grid";
  }
}

async function setMapMode(mode) {
  if(!["2d","25d"].includes(mode)||state.mapMode===mode)return;
  state.mapMode=mode;
  await loadFloorMap(state.selectedFloor, true);
  showToast(mode==="25d"?"2.5D map view":"2D map view");
}

function applyMapMode() {
  const is25d=state.mapMode==="25d";
  state.currentSvg?.classList.toggle("cn-map-25d",is25d);
  state.currentSvg?.classList.toggle("cn-map-2d",!is25d);
  document.body.dataset.mapMode=state.mapMode;
  document.querySelectorAll("[data-map-mode]").forEach(button=>{
    const active=button.dataset.mapMode===state.mapMode;
    button.classList.toggle("active",active);
    button.setAttribute("aria-pressed",String(active));
  });
  requestAnimationFrame(updateOverlayScale);
}

function enableClockwiseMapRotation(svg) {
  // Source geometry first rotates into the building's readable landscape
  // orientation. 2.5D then applies an asymmetric dimetric projection: the
  // plan axes become opposing diagonals with a slightly lower, bottom-right
  // camera. After the source's 90° rotation, a source-space (depth,-depth)
  // vector projects vertically, so the
  // wall and facility faces below read as construction rather than shadows.
  const source = getViewBox(svg);
  state.sourceViewBox = { ...source };

  const clockwise = document.createElementNS(SVG_NS, "g");
  clockwise.id = "campusnav-clockwise-map";
  clockwise.setAttribute(
    "transform",
    `matrix(0 1 -1 0 ${source.h + source.y} ${-source.x})`
  );

  const rotatedWidth = source.h;
  const rotatedHeight = source.w;
  const iso = state.mapMode === "25d";
  const projection = iso
    ? { a: .88, b: .34, c: -.88, d: .46, e: 0, f: 0 }
    : { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 };

  const corners = [
    [0, 0], [rotatedWidth, 0], [0, rotatedHeight], [rotatedWidth, rotatedHeight],
  ].map(([x, y]) => ({
    x: projection.a * x + projection.c * y,
    y: projection.b * x + projection.d * y,
  }));
  const minX = Math.min(...corners.map(point => point.x));
  const minY = Math.min(...corners.map(point => point.y));
  const maxX = Math.max(...corners.map(point => point.x));
  const maxY = Math.max(...corners.map(point => point.y));
  const pad = Math.min(rotatedWidth, rotatedHeight) * (iso ? .025 : 0);
  projection.e = -minX + pad;
  projection.f = -minY + pad;
  state.projectionMatrix = { ...projection };

  const projectionGroup = document.createElementNS(SVG_NS, "g");
  projectionGroup.id = "campusnav-map-projection";
  projectionGroup.setAttribute(
    "transform",
    `matrix(${projection.a} ${projection.b} ${projection.c} ${projection.d} ${projection.e} ${projection.f})`
  );

  // Keep non-rendered document resources at root level. All architectural
  // geometry shares the same projection; labels and route overlays are added
  // later in already-projected root coordinates so their glyphs stay upright.
  const rootOnly = new Set(["defs", "metadata", "title", "desc", "namedview"]);
  [...svg.childNodes].forEach((node) => {
    if (node.nodeType === 1 && rootOnly.has(String(node.localName || "").toLowerCase())) return;
    clockwise.appendChild(node);
  });

  projectionGroup.appendChild(clockwise);
  svg.appendChild(projectionGroup);
  const bounds = {
    x: 0,
    y: 0,
    w: maxX - minX + pad * 2,
    h: maxY - minY + pad * 2,
  };
  svg.setAttribute("viewBox", `0 0 ${bounds.w} ${bounds.h}`);
  state.rotationGroup = clockwise;

  return bounds;
}

function sourcePointToDisplay(x, y) {
  const source = state.sourceViewBox;
  if (!source) return { x, y };
  const rotated = {
    x: source.h + source.y - y,
    y: x - source.x,
  };
  const matrix = state.projectionMatrix || { a:1, b:0, c:0, d:1, e:0, f:0 };
  return {
    x: matrix.a * rotated.x + matrix.c * rotated.y + matrix.e,
    y: matrix.b * rotated.x + matrix.d * rotated.y + matrix.f,
  };
}


function decorateBlueprint(svg, floorId) {
  buildAccessSymbols(svg, floorId);
  hideTechnicalGraph(svg);
  const wallLayer = findLayer(svg, /map[\s_-]*walls/);
  wallLayer?.classList.add("cn-architecture");
  buildOpenSpaceSurfaces(svg, wallLayer, floorId);
  buildWallDepth(svg, wallLayer);
  buildWallOutline(svg, wallLayer);
  colorInfrastructure(svg, floorId);
  colorRoomLabels(svg, floorId);
  buildSpaceDepth(svg);
}

function buildWallDepth(svg, wallLayer) {
  if (!wallLayer?.parentNode) return;
  const size = Math.min(getViewBox(svg).w, getViewBox(svg).h);
  const scaleCorrection = svg.dataset.floor === "F3" ? 1.5 : 1;
  const depth = size * 0.016 * scaleCorrection;
  const wallWidth = size * 0.0028 * Math.min(scaleCorrection, 1.2);
  svg.style.setProperty("--cn-wall-top-width", `${wallWidth}px`);
  const depthGroup = document.createElementNS(SVG_NS, "g");
  depthGroup.id = "campusnav-wall-depth";
  depthGroup.setAttribute("class", "cn-wall-depth");
  depthGroup.setAttribute("aria-hidden", "true");

  // Sweep every wall segment into one exact vertical face. This produces a
  // solid architectural edge with hard joins, not a stack of offset strokes.
  appendExtrudedFaces(
    svg,
    wallLayer,
    depthGroup,
    depth,
    "cn-wall-face",
    "path:not(.cn-flat-boundary),line:not(.cn-flat-boundary),polyline:not(.cn-flat-boundary),polygon:not(.cn-flat-boundary),rect:not(.cn-flat-boundary)"
  );
  wallLayer.parentNode.insertBefore(depthGroup, wallLayer);
}

function buildWallOutline(svg, wallLayer) {
  if (!wallLayer?.parentNode) return;
  const outline = document.createElementNS(SVG_NS, "g");
  outline.id = "campusnav-wall-outline";
  outline.setAttribute("class", "cn-wall-outline");
  outline.setAttribute("aria-hidden", "true");
  const selector = "path:not(.cn-flat-boundary),line:not(.cn-flat-boundary),polyline:not(.cn-flat-boundary),polygon:not(.cn-flat-boundary),rect:not(.cn-flat-boundary)";
  for (const shape of wallLayer.querySelectorAll(selector)) {
    const clone = shape.cloneNode(false);
    clone.removeAttribute("id");
    clone.removeAttribute("style");
    clone.removeAttribute("fill");
    clone.removeAttribute("stroke");
    clone.setAttribute("class", "cn-wall-outline-shape");
    outline.appendChild(clone);
  }
  wallLayer.parentNode.insertBefore(outline, wallLayer);
}

function buildSpaceDepth(svg) {
  const size = Math.min(getViewBox(svg).w, getViewBox(svg).h);
  const depth = size * 0.013;
  const layers = [
    findLayer(svg, /map[\s_-]*rooms/),
    findLayer(svg, /map[\s_-]*infrastructure/),
  ].filter(Boolean);

  for (const layer of layers) {
    if (!layer.parentNode || !layer.querySelector(".cn-facility")) continue;
    const group = document.createElementNS(SVG_NS, "g");
    group.setAttribute("class", "cn-space-depth");
    group.setAttribute("aria-hidden", "true");
    appendExtrudedFaces(svg, layer, group, depth, "cn-space-face", ".cn-facility");
    layer.parentNode.insertBefore(group, layer);
  }
}

function appendExtrudedFaces(svg, sourceLayer, targetGroup, depth, faceClass, selector = "path,line,polyline,polygon,rect") {
  for (const shape of sourceLayer.querySelectorAll(selector)) {
    for (const [start, end] of geometrySegments(shape, sourceLayer, svg)) {
      const length = Math.hypot(end.x - start.x, end.y - start.y);
      if (length < .05) continue;
      const face = document.createElementNS(SVG_NS, "polygon");
      face.setAttribute(
        "points",
        `${start.x},${start.y} ${end.x},${end.y} ${end.x + depth},${end.y - depth} ${start.x + depth},${start.y - depth}`
      );
      face.setAttribute("class", faceClass);
      const sourceDx = end.x - start.x;
      const sourceDy = end.y - start.y;
      const rotatedDx = -sourceDy;
      const rotatedDy = sourceDx;
      const screenDx = (state.projectionMatrix?.a ?? .88) * rotatedDx
        + (state.projectionMatrix?.c ?? -.88) * rotatedDy;
      face.dataset.faceShade = screenDx > .1 ? "right" : screenDx < -.1 ? "left" : "front";
      targetGroup.appendChild(face);
    }
  }
}

function geometrySegments(shape, targetLayer, svg) {
  const name = shape.localName?.toLowerCase();
  let points = [];
  let closed = false;

  if (name === "line") {
    points = [
      { x: Number(shape.getAttribute("x1")) || 0, y: Number(shape.getAttribute("y1")) || 0 },
      { x: Number(shape.getAttribute("x2")) || 0, y: Number(shape.getAttribute("y2")) || 0 },
    ];
  } else if (name === "rect") {
    const x = Number(shape.getAttribute("x")) || 0;
    const y = Number(shape.getAttribute("y")) || 0;
    const w = Number(shape.getAttribute("width")) || 0;
    const h = Number(shape.getAttribute("height")) || 0;
    points = [{x,y},{x:x+w,y},{x:x+w,y:y+h},{x,y:y+h}];
    closed = true;
  } else if (name === "polygon" || name === "polyline") {
    points = [...shape.points].map(point => ({ x: point.x, y: point.y }));
    closed = name === "polygon";
  } else if (typeof shape.getTotalLength === "function") {
    let total = 0;
    try { total = shape.getTotalLength(); } catch { total = 0; }
    if (!Number.isFinite(total) || total <= 0) return [];
    const sampleCount = Math.max(2, Math.min(260, Math.ceil(total / 8)));
    for (let index = 0; index <= sampleCount; index += 1) {
      const point = shape.getPointAtLength(total * index / sampleCount);
      points.push({ x: point.x, y: point.y });
    }
    closed = isClosedShape(shape);
  }

  const sourceMatrix = shape.getCTM();
  const targetMatrix = targetLayer.getCTM();
  if (!sourceMatrix || !targetMatrix || points.length < 2) return [];
  const relative = targetMatrix.inverse().multiply(sourceMatrix);
  points = points.map(point => {
    const converted = new DOMPoint(point.x, point.y).matrixTransform(relative);
    return { x: converted.x, y: converted.y };
  });

  const segments = [];
  for (let index = 1; index < points.length; index += 1) {
    segments.push([points[index - 1], points[index]]);
  }
  if (closed && Math.hypot(points[0].x - points.at(-1).x, points[0].y - points.at(-1).y) > .05) {
    segments.push([points.at(-1), points[0]]);
  }
  return segments;
}

function layerToken(group) {
  return normalizeText(`${group?.id || ""} ${group?.getAttributeNS?.(INKSCAPE_NS,"label") || group?.getAttribute?.("inkscape:label") || ""}`);
}
function findLayer(svg, pattern) {
  return [...svg.querySelectorAll("g")].find(group=>pattern.test(layerToken(group))) || null;
}

function buildOpenSpaceSurfaces(svg, wallLayer, floorId) {
  if (!wallLayer?.parentNode) return;
  const boundaries=[...wallLayer.querySelectorAll("path,rect,polygon,polyline")].filter(shape=>{
    const paint=`${shape.getAttribute("style")||""} ${shape.getAttribute("stroke")||""}`;
    return /#00aad4|#00aaff|#3cb1df|#449ad6/i.test(paint);
  });
  if (!boundaries.length) return;
  boundaries.forEach(shape=>shape.classList.add("cn-flat-boundary"));

  const boxes=boundaries.map(shape=>boundsInLayer(shape,wallLayer)).filter(box=>box&&box.w>0&&box.h>0);
  const components=[];
  for(const box of boxes) {
    const touching=components.filter(component=>boxesTouch(component,box,6));
    if(!touching.length) {
      components.push({...box});
      continue;
    }
    const merged=touching.reduce((result,component)=>unionBoxes(result,component),box);
    touching.forEach(component=>components.splice(components.indexOf(component),1));
    components.push(merged);
  }

  const minimumSize=Math.min(getViewBox(svg).w,getViewBox(svg).h)*.012;
  const regions=blueprintFlatSpaceRegions(
    floorId,
    components.filter(box=>box.w>=minimumSize&&box.h>=minimumSize)
  );
  const group=document.createElementNS(SVG_NS,"g");
  group.id="campusnav-open-spaces";
  group.setAttribute("class","cn-open-space-layer cn-flat-space-layer");
  group.setAttributeNS(INKSCAPE_NS,"inkscape:label","MAP - Flat open and seating spaces");
  const fontSize=Math.min(getViewBox(svg).w,getViewBox(svg).h)*.0082;
  let count=0;
  for(const region of regions) {
    const {box,kind}=region;
    count+=1;
    const surface=document.createElementNS(SVG_NS,"rect");
    surface.setAttribute("x",box.x);surface.setAttribute("y",box.y);
    surface.setAttribute("width",box.w);surface.setAttribute("height",box.h);
    surface.setAttribute("class",`cn-open-space-surface cn-flat-space-${kind}`);
    surface.dataset.flatSpaceKind=kind;
    surface.dataset.flatSpaceIndex=String(count);
    const accessibleName=kind==="seating"?"Cut-out seating / break-out space":"Open-to-sky courtyard";
    surface.setAttribute("aria-label",`${accessibleName} ${count} on ${floorName(floorId)}`);
    group.appendChild(surface);
    if (kind === "seating") appendSeatingDetail(group, box, count);
    if (kind === "open") appendOpenSpacePerimeter(group, box, count);

    const label=document.createElementNS(SVG_NS,"text");
    label.setAttribute("x",box.x+box.w/2);label.setAttribute("y",box.y+box.h/2-fontSize*.18);
    label.setAttribute("text-anchor","middle");label.style.fontSize=`${fontSize}px`;
    label.setAttribute("class",`cn-open-space-label cn-flat-space-label-${kind}`);
    label.dataset.flatSpaceKind=kind;
    const title=document.createElementNS(SVG_NS,"tspan");
    title.setAttribute("x",box.x+box.w/2);
    title.textContent=kind==="seating"?"SEATING DECK":"OPEN TO SKY";
    label.appendChild(title);
    const subtitle=document.createElementNS(SVG_NS,"tspan");
    subtitle.setAttribute("x",box.x+box.w/2);subtitle.setAttribute("dy","1.25em");
    subtitle.setAttribute("class","cn-label-type");
    subtitle.textContent=kind==="seating"?"Benches · tables":"Flat courtyard";
    label.appendChild(subtitle);
    group.appendChild(label);
  }
  if(!count)return;
  const corridor=svg.querySelector("#campusnav-floor-corridors");
  wallLayer.parentNode.insertBefore(group,corridor||wallLayer);
}

function appendOpenSpacePerimeter(group, box, index) {
  const perimeter=document.createElementNS(SVG_NS,"g");
  perimeter.setAttribute("class","cn-open-perimeter");
  perimeter.dataset.openPerimeterIndex=String(index);
  perimeter.setAttribute("aria-hidden","true");
  const inset=Math.min(box.w,box.h)*.025;
  const x=box.x+inset,y=box.y+inset,w=Math.max(1,box.w-inset*2),h=Math.max(1,box.h-inset*2);
  for(const className of ["cn-open-perimeter-base","cn-open-perimeter-cap"]) {
    const rail=document.createElementNS(SVG_NS,"rect");
    rail.setAttribute("x",x);rail.setAttribute("y",y);
    rail.setAttribute("width",w);rail.setAttribute("height",h);
    rail.setAttribute("rx",Math.min(w,h)*.025);
    rail.setAttribute("class",className);
    perimeter.appendChild(rail);
  }
  const postSize=Math.min(w,h)*.035;
  for(const [px,py] of [[x,y],[x+w,y],[x,y+h],[x+w,y+h]]) {
    const post=document.createElementNS(SVG_NS,"rect");
    post.setAttribute("x",px-postSize/2);post.setAttribute("y",py-postSize/2);
    post.setAttribute("width",postSize);post.setAttribute("height",postSize);
    post.setAttribute("rx",postSize*.18);post.setAttribute("class","cn-open-perimeter-post");
    perimeter.appendChild(post);
  }
  group.appendChild(perimeter);
}

function appendSeatingDetail(group, box, index) {
  const detail=document.createElementNS(SVG_NS,"g");
  detail.setAttribute("class","cn-seating-detail");
  detail.dataset.seatingIndex=String(index);
  detail.setAttribute("aria-hidden","true");
  const inset=Math.min(box.w,box.h)*.09;
  const inner={x:box.x+inset,y:box.y+inset,w:Math.max(1,box.w-inset*2),h:Math.max(1,box.h-inset*2)};

  const deck=document.createElementNS(SVG_NS,"rect");
  deck.setAttribute("x",inner.x);deck.setAttribute("y",inner.y);
  deck.setAttribute("width",inner.w);deck.setAttribute("height",inner.h);
  deck.setAttribute("rx",Math.min(inner.w,inner.h)*.05);
  deck.setAttribute("class","cn-seating-deck");
  detail.appendChild(deck);

  const horizontal=inner.w>=inner.h;
  for(let step=1;step<9;step++) {
    const line=document.createElementNS(SVG_NS,"line");
    if(horizontal) {
      const x=inner.x+inner.w*step/9;
      line.setAttribute("x1",x);line.setAttribute("y1",inner.y);
      line.setAttribute("x2",x);line.setAttribute("y2",inner.y+inner.h);
    } else {
      const y=inner.y+inner.h*step/9;
      line.setAttribute("x1",inner.x);line.setAttribute("y1",y);
      line.setAttribute("x2",inner.x+inner.w);line.setAttribute("y2",y);
    }
    line.setAttribute("class","cn-seating-slat");
    detail.appendChild(line);
  }

  const benchWidth=horizontal?inner.w*.22:inner.w*.14;
  const benchHeight=horizontal?inner.h*.12:inner.h*.24;
  const benchPositions=horizontal
    ? [[inner.x+inner.w*.08,inner.y+inner.h*.14],[inner.x+inner.w*.70,inner.y+inner.h*.74]]
    : [[inner.x+inner.w*.12,inner.y+inner.h*.08],[inner.x+inner.w*.74,inner.y+inner.h*.68]];
  for(const [x,y] of benchPositions) {
    const bench=document.createElementNS(SVG_NS,"rect");
    bench.setAttribute("x",x);bench.setAttribute("y",y);
    bench.setAttribute("width",benchWidth);bench.setAttribute("height",benchHeight);
    bench.setAttribute("rx",Math.min(benchWidth,benchHeight)*.18);
    bench.setAttribute("class","cn-seating-bench");
    detail.appendChild(bench);
  }

  const table=document.createElementNS(SVG_NS,"circle");
  const tableX=inner.x+inner.w*.76,tableY=inner.y+inner.h*.28;
  const tableRadius=Math.min(inner.w,inner.h)*.075;
  table.setAttribute("cx",tableX);table.setAttribute("cy",tableY);
  table.setAttribute("r",tableRadius);table.setAttribute("class","cn-seating-table");
  detail.appendChild(table);
  for(const [dx,dy] of [[-2,0],[2,0],[0,-2],[0,2]]) {
    const chair=document.createElementNS(SVG_NS,"circle");
    chair.setAttribute("cx",tableX+dx*tableRadius);
    chair.setAttribute("cy",tableY+dy*tableRadius);
    chair.setAttribute("r",tableRadius*.34);
    chair.setAttribute("class","cn-seating-chair");
    detail.appendChild(chair);
  }
  group.appendChild(detail);
}

function flatRegion(box,kind) {
  return {box:{...box},kind};
}

function splitFlatRegion(box,fraction,firstKind,secondKind) {
  const firstHeight=box.h*fraction;
  return [
    flatRegion({...box,h:firstHeight},firstKind),
    flatRegion({...box,y:box.y+firstHeight,h:box.h-firstHeight},secondKind),
  ];
}

function blueprintFlatSpaceRegions(floorId,components) {
  const sorted=[...components].sort((a,b)=>a.y-b.y||a.x-b.x);
  if(!sorted.length)return [];

  // The simplified SVG joins the lower cut-out and courtyard on these floors.
  // Split that long boundary where the architectural plan changes from the
  // seating/break-out zone to the open-to-sky courtyard.
  if(["G","F1","F4","F5"].includes(floorId)&&sorted.length===3) {
    const [top,middle,bottom]=sorted;
    return [flatRegion(top,"open"),flatRegion(middle,"open"),
      ...splitFlatRegion(bottom,.63,"seating","open")];
  }
  if(floorId==="F2"&&sorted.length>=4) {
    return sorted.map((box,index)=>flatRegion(box,index===1?"seating":"open"));
  }
  if(floorId==="F6"&&sorted.length===3) {
    const [combined,middle,bottom]=sorted;
    return [...splitFlatRegion(combined,.58,"open","seating"),
      flatRegion(middle,"open"),flatRegion(bottom,"open")];
  }
  if(floorId==="F7"&&sorted.length>=3) {
    return sorted.map((box,index)=>flatRegion(box,index===1?"seating":"open"));
  }
  if(floorId==="F3"&&sorted.length===1) {
    return splitFlatRegion(sorted[0],.52,"open","seating");
  }
  if(floorId==="F3") {
    return sorted.map((box,index)=>flatRegion(box,index===1?"seating":"open"));
  }
  return sorted.map(box=>flatRegion(box,"open"));
}

function boundsInLayer(shape,layer) {
  const box=shape.getBBox(),shapeMatrix=shape.getCTM(),layerMatrix=layer.getCTM();
  if(!shapeMatrix||!layerMatrix)return null;
  const matrix=layerMatrix.inverse().multiply(shapeMatrix);
  const corners=[[box.x,box.y],[box.x+box.width,box.y],[box.x,box.y+box.height],[box.x+box.width,box.y+box.height]]
    .map(([x,y])=>new DOMPoint(x,y).matrixTransform(matrix));
  const xs=corners.map(point=>point.x),ys=corners.map(point=>point.y);
  return {x:Math.min(...xs),y:Math.min(...ys),w:Math.max(...xs)-Math.min(...xs),h:Math.max(...ys)-Math.min(...ys)};
}

function boxesTouch(a,b,gap=0) {
  return a.x<=b.x+b.w+gap&&a.x+a.w+gap>=b.x&&a.y<=b.y+b.h+gap&&a.y+a.h+gap>=b.y;
}

function unionBoxes(a,b) {
  const x=Math.min(a.x,b.x),y=Math.min(a.y,b.y);
  return {x,y,w:Math.max(a.x+a.w,b.x+b.w)-x,h:Math.max(a.y+a.h,b.y+b.h)-y};
}

function labelLocalAnchor(label) {
  const span=label.querySelector("tspan[x],tspan[y]");
  const rawX=label.getAttribute("x")??span?.getAttribute("x");
  const rawY=label.getAttribute("y")??span?.getAttribute("y");
  const x=parseFloat(rawX),y=parseFloat(rawY);
  if(Number.isFinite(x)&&Number.isFinite(y))return {x,y};
  const box=label.getBBox();
  return {x:box.x+box.width/2,y:box.y+box.height/2};
}
function pointInRoot(element,x,y,svg) {
  const matrix=svg.getCTM()?.inverse().multiply(element.getCTM());
  return matrix ? new DOMPoint(x,y).matrixTransform(matrix) : null;
}
function labelAnchorInRoot(label,svg) {
  const local=labelLocalAnchor(label);
  return pointInRoot(label,local.x,local.y,svg);
}
function collectNavNodes(layer,floorId,svg) {
  if (!layer) return [];
  return [...layer.querySelectorAll("circle,ellipse")].map(shape=>{
    const p=pointInRoot(shape,Number(shape.getAttribute("cx")),Number(shape.getAttribute("cy")),svg);
    return p ? {id:shape.id,x:p.x,y:p.y} : null;
  }).filter(Boolean);
}
function nearestNavNode(point,nodes) {
  if(!point)return null;
  let best=null,distance=Infinity;
  for (const node of nodes) {
    const d=Math.hypot(node.x-point.x,node.y-point.y);
    if (d<distance) {best=node;distance=d;}
  }
  return distance<=CORRIDOR_NODE_MATCH_TOLERANCE ? best : null;
}

function normalizedSourceNodeId(id,floorId) {
  const floorPrefix=new RegExp(`^${String(floorId).replace(/[.*+?^${}()|[\]\\]/g,"\\$&")}_`,"i");
  return String(id||"").replace(floorPrefix,"").toUpperCase();
}

function buildNavAdjacency(svg,floorId) {
  const nodeLayer=findLayer(svg,/nav[\s_-]*nodes/),edgeLayer=findLayer(svg,/nav[\s_-]*edges/);
  const nodes=collectNavNodes(nodeLayer,floorId,svg),adjacency=new Map();
  const byId=new Map(nodes.map(node=>[node.id,node]));
  if(!edgeLayer)return {nodes,adjacency,byId};
  const connect=(a,b)=>{
    if(!adjacency.has(a.id))adjacency.set(a.id,[]);
    adjacency.get(a.id).push(b);
  };
  for(const edge of edgeLayer.querySelectorAll("path,line,polyline")) {
    if(typeof edge.getTotalLength!=="function")continue;
    const length=edge.getTotalLength();
    if(!Number.isFinite(length)||length<=0)continue;
    const start=edge.getPointAtLength(0),end=edge.getPointAtLength(length);
    const aPoint=pointInRoot(edge,start.x,start.y,svg),bPoint=pointInRoot(edge,end.x,end.y,svg);
    const a=nearestNavNode(aPoint,nodes),b=nearestNavNode(bPoint,nodes);
    if(!a||!b||a.id===b.id)continue;
    connect(a,b);connect(b,a);
  }
  return {nodes,adjacency,byId};
}

function buildAccessSymbols(svg,floorId) {
  const {nodes,adjacency}=buildNavAdjacency(svg,floorId);
  if(!nodes.length)return;
  const group=document.createElementNS(SVG_NS,"g");
  group.id="campusnav-access-symbols";
  group.setAttribute("class","cn-access-layer");
  group.setAttributeNS(INKSCAPE_NS,"inkscape:label","MAP - Access Symbols");
  group.setAttribute("pointer-events","none");
  const size=Math.min(getViewBox(svg).w,getViewBox(svg).h);
  const locations=state.locationsByFloor.get(floorId)||[];
  const roomNodes=new Set();
  const roomKinds=new Map();
  for(const location of locations) {
    const key=locationKey(location.code);
    for(const node of nodes) {
      const source=normalizedSourceNodeId(node.id,floorId);
      if(source===key||source.startsWith(`${key}-`)) {
        roomNodes.add(node.id);
        roomKinds.set(node.id,semanticRoomClass(location));
      }
    }
  }

  const drawRoomDoor=(node,neighbor,kind)=>{
    const dx=neighbor.x-node.x,dy=neighbor.y-node.y,length=Math.hypot(dx,dy);
    if(length<.001)return;
    const ux=dx/length,uy=dy/length,px=-uy,py=ux,half=size*.0065;
    const door=document.createElementNS(SVG_NS,"g");
    door.setAttribute("class","cn-room-door");door.dataset.nodeId=node.id;door.dataset.roomKind=kind;
    const threshold=document.createElementNS(SVG_NS,"line");
    threshold.setAttribute("x1",node.x-px*half);threshold.setAttribute("y1",node.y-py*half);
    threshold.setAttribute("x2",node.x+px*half);threshold.setAttribute("y2",node.y+py*half);
    threshold.setAttribute("class","cn-room-door-threshold");door.appendChild(threshold);
    const leaf=document.createElementNS(SVG_NS,"line");
    leaf.setAttribute("x1",node.x-px*half);leaf.setAttribute("y1",node.y-py*half);
    leaf.setAttribute("x2",node.x+px*half*.72-ux*half*.72);
    leaf.setAttribute("y2",node.y+py*half*.72-uy*half*.72);
    leaf.setAttribute("class","cn-room-door-leaf");door.appendChild(leaf);
    const jambA=document.createElementNS(SVG_NS,"rect"),jambB=document.createElementNS(SVG_NS,"rect");
    for(const [jamb,sign] of [[jambA,-1],[jambB,1]]) {
      const post=size*.0024;
      jamb.setAttribute("x",node.x+px*half*sign-post/2);
      jamb.setAttribute("y",node.y+py*half*sign-post/2);
      jamb.setAttribute("width",post);jamb.setAttribute("height",post);
      jamb.setAttribute("class","cn-room-door-jamb");door.appendChild(jamb);
    }
    group.appendChild(door);
  };

  for(const node of nodes) {
    const source=normalizedSourceNodeId(node.id,floorId);
    const neighbors=adjacency.get(node.id)||[];
    if(/ENTRANCE/.test(source)) {
      const neighbor=neighbors.find(item=>!/ENTRANCE/.test(normalizedSourceNodeId(item.id,floorId)))||neighbors[0];
      if(!neighbor)continue;
      const dx=neighbor.x-node.x,dy=neighbor.y-node.y,length=Math.hypot(dx,dy);
      if(length<.001)continue;
      const ux=dx/length,uy=dy/length,px=-uy,py=ux,half=size*.014,depth=size*.012;
      const entry=document.createElementNS(SVG_NS,"g");
      entry.setAttribute("class","cn-building-entrance");entry.dataset.nodeId=node.id;
      const mat=document.createElementNS(SVG_NS,"polygon");
      mat.setAttribute("points",[
        [node.x-px*half,node.y-py*half],[node.x+px*half,node.y+py*half],
        [node.x+px*half+ux*depth,node.y+py*half+uy*depth],[node.x-px*half+ux*depth,node.y-py*half+uy*depth]
      ].map(point=>point.join(",")).join(" "));
      mat.setAttribute("class","cn-entrance-mat");entry.appendChild(mat);
      const gate=document.createElementNS(SVG_NS,"line");
      gate.setAttribute("x1",node.x-px*half);gate.setAttribute("y1",node.y-py*half);
      gate.setAttribute("x2",node.x+px*half);gate.setAttribute("y2",node.y+py*half);
      gate.setAttribute("class","cn-entrance-gate");entry.appendChild(gate);
      for(const sign of [-1,1]) {
        const post=document.createElementNS(SVG_NS,"circle");
        post.setAttribute("cx",node.x+px*half*sign);post.setAttribute("cy",node.y+py*half*sign);
        post.setAttribute("r",size*.0032);post.setAttribute("class","cn-entrance-post");entry.appendChild(post);
      }
      const arrow=document.createElementNS(SVG_NS,"polygon");
      const tip={x:node.x+ux*depth*.82,y:node.y+uy*depth*.82};
      const base={x:node.x+ux*depth*.28,y:node.y+uy*depth*.28};
      const arrowHalf=size*.0038;
      arrow.setAttribute("points",`${tip.x},${tip.y} ${base.x+px*arrowHalf},${base.y+py*arrowHalf} ${base.x-px*arrowHalf},${base.y-py*arrowHalf}`);
      arrow.setAttribute("class","cn-entrance-arrow");entry.appendChild(arrow);
      const label=document.createElementNS(SVG_NS,"text");
      label.setAttribute("x",node.x-ux*size*.018);label.setAttribute("y",node.y-uy*size*.018);
      label.setAttribute("text-anchor","middle");label.style.fontSize=`${size*.008}px`;
      label.setAttribute("class","cn-access-label cn-entrance-label");
      const number=(source.match(/ENTRANCE(\d+)/)||[])[1]||"";
      label.textContent=`ENTRY ${number}`.trim();entry.appendChild(label);
      group.appendChild(entry);
      continue;
    }
    if(!roomNodes.has(node.id))continue;
    const roomKind=roomKinds.get(node.id)||"unknown";
    if(roomKind==="classroom")continue;
    const neighbor=neighbors.find(item=>!roomNodes.has(item.id)&&!/^(LIFT|STAIR|ENTRANCE)/.test(normalizedSourceNodeId(item.id,floorId)))||neighbors[0];
    if(neighbor)drawRoomDoor(node,neighbor,roomKind);
  }
  if(group.childElementCount)svg.appendChild(group);
}
function pointToSegmentDistance(p,a,b) {
  const dx=b.x-a.x,dy=b.y-a.y;
  const t=dx||dy ? Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.y-a.y)*dy)/(dx*dx+dy*dy))) : 0;
  return Math.hypot(p.x-a.x-t*dx,p.y-a.y-t*dy);
}
function segmentClearance(a,b,c,d) {
  const cross=(p,q,r)=>(q.x-p.x)*(r.y-p.y)-(q.y-p.y)*(r.x-p.x);
  if (cross(a,b,c)*cross(a,b,d)<0 && cross(c,d,a)*cross(c,d,b)<0) return 0;
  return Math.min(pointToSegmentDistance(a,c,d),pointToSegmentDistance(b,c,d),
    pointToSegmentDistance(c,a,b),pointToSegmentDistance(d,a,b));
}
function buildWholeFloorCorridorNetwork(svg,floorId) {
  // F2 is the visual pilot; other floors retain their approved presentation.
  if (floorId === "F2") return buildF2CorridorSurface(svg);
  const nodeLayer=findLayer(svg,/nav[\s_-]*nodes/),edgeLayer=findLayer(svg,/nav[\s_-]*edges/),
    wallLayer=findLayer(svg,/map[\s_-]*walls/);
  if (!nodeLayer || !edgeLayer || !wallLayer) return;
  // Unknown node purposes and all room/connector spurs are excluded.
  const nodes=collectNavNodes(nodeLayer,floorId,svg);
  const mapSize=Math.min(getViewBox(svg).w,getViewBox(svg).h);
  const clearanceWidth=mapSize*.012;
  const width=mapSize*.019;
  const destinationIds=new Set((state.locationsByFloor.get(floorId)||[]).map(item=>String(item.code)));
  findLayer(svg,/map[\s_-]*rooms/)?.querySelectorAll("text").forEach(label=>destinationIds.add(label.textContent.trim()));
  // Integrated metadata prefixes some identifiers; the source SVG retains
  // their unprefixed IDs. This affects presentation lookup only.
  const hallwayIds=new Set((window.CAMPUSNAV_HALLWAY_IDS?.[floorId]||[]).flatMap(id=>[
    id, id.startsWith(`${floorId}_`) ? id.slice(floorId.length+1) : id
  ]));
  const isHallway=id=>hallwayIds.has(id) && !destinationIds.has(id) && !/^(ENTRANCE|LIFT|STAIR)/i.test(id);
  const walls=[],sampleStep=clearanceWidth/5;
  for (const shape of wallLayer.querySelectorAll("path,line,polyline,polygon,rect")) {
    if (typeof shape.getTotalLength!=="function") continue;
    const length=shape.getTotalLength(),count=Math.max(1,Math.ceil(length/sampleStep));
    let previous=null;
    for (let i=0;i<=count;i++) {
      const p=shape.getPointAtLength(length*i/count),point=pointInRoot(shape,p.x,p.y,svg);
      if (point && previous) walls.push([previous,point]);
      previous=point;
    }
  }
  if (!walls.length) return;
  const accepted=[],adjacency=new Map();
  for (const edge of edgeLayer.querySelectorAll("path,line,polyline")) {
    if (typeof edge.getTotalLength!=="function") continue;
    const length=edge.getTotalLength(),p=edge.getPointAtLength(0),q=edge.getPointAtLength(length);
    const a=pointInRoot(edge,p.x,p.y,svg),b=pointInRoot(edge,q.x,q.y,svg);
    if (!a || !b || length<clearanceWidth/2) continue;
    const na=nearestNavNode(a,nodes),nb=nearestNavNode(b,nodes);
    if (!na || !nb || !isHallway(na.id) || !isHallway(nb.id)) continue;
    // Reject curved or multi-turn edges rather than inventing a straight shortcut.
    let straight=true;
    for (let i=1;i<8;i++) {
      const p=edge.getPointAtLength(length*i/8),v=pointInRoot(edge,p.x,p.y,svg);
      if (!v || pointToSegmentDistance(v,a,b)>clearanceWidth*.02) {straight=false;break;}
    }
    if (!straight) continue;
    const margin=clearanceWidth*.8;
    const nearby=walls.filter(([c,d])=>Math.max(c.x,d.x)>=Math.min(a.x,b.x)-margin &&
      Math.min(c.x,d.x)<=Math.max(a.x,b.x)+margin && Math.max(c.y,d.y)>=Math.min(a.y,b.y)-margin &&
      Math.min(c.y,d.y)<=Math.max(a.y,b.y)+margin);
    if (nearby.some(([c,d])=>segmentClearance(a,b,c,d)<margin)) continue;
    const index=accepted.length;
    accepted.push({a,b,na:na.id,nb:nb.id});
    for (const id of [na.id,nb.id]) {
      if(!adjacency.has(id))adjacency.set(id,[]);
      adjacency.get(id).push(index);
    }
  }
  if (!accepted.length) return;
  const group=document.createElementNS(SVG_NS,"g");
  group.id="campusnav-floor-corridors";
  group.setAttribute("aria-hidden","true");
  group.dataset.corridorStyle="continuous-banded-network";
  group.style.setProperty("--hallway-width",`${width}px`);
  group.style.setProperty("--hallway-border-width",`${width+mapSize*.0048}px`);
  group.style.setProperty("--hallway-center-width",`${Math.max(1,mapSize*.0012)}px`);
  // Connected runs use one broad band, a crisp boundary, and a subtle dashed
  // wayfinding center. Rounded run ends overlap cleanly at corridor junctions.
  const visited=new Set();
  function trace(start,index) {
    const points=[];let id=start;
    while(!visited.has(index)) {
      visited.add(index);
      const e=accepted[index],forward=e.na===id;
      if(!points.length)points.push(forward?e.a:e.b);
      points.push(forward?e.b:e.a);
      id=forward?e.nb:e.na;
      const next=adjacency.get(id);
      if(next.length!==2)break;
      index=next.find(i=>!visited.has(i));
      if(index===undefined)break;
    }
    const pointString=points.map(p=>`${p.x},${p.y}`).join(" ");
    for(const className of ["cn-hallway-border","cn-hallway","cn-hallway-centerline"]) {
      const road=document.createElementNS(SVG_NS,"polyline");
      road.setAttribute("points",pointString);
      road.setAttribute("class",className);
      group.appendChild(road);
    }
  }
  for(const[id,edges]of adjacency)if(edges.length!==2)edges.forEach(i=>{if(!visited.has(i))trace(id,i);});
  accepted.forEach((e,i)=>{if(!visited.has(i))trace(e.na,i);});
  svg.insertBefore(group,wallLayer);
}

function corridorUnionContours(polygons) {
  const cross=(a,b)=>a.x*b.y-a.y*b.x,epsilon=.00001;
  const bounds=p=>({minX:Math.min(...p.map(v=>v.x)),maxX:Math.max(...p.map(v=>v.x)),
    minY:Math.min(...p.map(v=>v.y)),maxY:Math.max(...p.map(v=>v.y))});
  const prepared=polygons.map(points=>{
    const area=points.reduce((sum,p,i)=>sum+cross(p,points[(i+1)%points.length]),0);
    return {points:area<0?[...points].reverse():points,...bounds(points)};
  }).filter(p=>p.points.length>=3);
  function occupied(point) {
    return prepared.some(p=>{
      if(point.x<p.minX-epsilon||point.x>p.maxX+epsilon||point.y<p.minY-epsilon||point.y>p.maxY+epsilon)return false;
      return p.points.every((a,i)=>{
        const b=p.points[(i+1)%p.points.length];
        return cross({x:b.x-a.x,y:b.y-a.y},{x:point.x-a.x,y:point.y-a.y})>=-epsilon;
      });
    });
  }
  const edges=prepared.flatMap(p=>p.points.map((a,i)=>({a,b:p.points[(i+1)%p.points.length]})));
  const boundary=new Map(),key=p=>`${p.x.toFixed(5)},${p.y.toFixed(5)}`;
  for(const {a,b}of edges) {
    const v={x:b.x-a.x,y:b.y-a.y},size=Math.hypot(v.x,v.y);
    if(size<epsilon)continue;
    const cuts=[0,1];
    for(const {a:c,b:d}of edges) {
      if(Math.max(c.x,d.x)<Math.min(a.x,b.x)-epsilon||Math.min(c.x,d.x)>Math.max(a.x,b.x)+epsilon||
         Math.max(c.y,d.y)<Math.min(a.y,b.y)-epsilon||Math.min(c.y,d.y)>Math.max(a.y,b.y)+epsilon)continue;
      const w={x:d.x-c.x,y:d.y-c.y},q={x:c.x-a.x,y:c.y-a.y},den=cross(v,w);
      if(Math.abs(den)>epsilon) {
        const t=cross(q,w)/den,u=cross(q,v)/den;
        if(t>epsilon&&t<1-epsilon&&u>=-epsilon&&u<=1+epsilon)cuts.push(t);
      } else if(Math.abs(cross(q,v))<epsilon) {
        for(const p of [c,d]) {
          const t=((p.x-a.x)*v.x+(p.y-a.y)*v.y)/(size*size);
          if(t>epsilon&&t<1-epsilon)cuts.push(t);
        }
      }
    }
    cuts.sort((x,y)=>x-y);
    for(let i=1;i<cuts.length;i++) {
      if((cuts[i]-cuts[i-1])*size<epsilon)continue;
      const t=(cuts[i]+cuts[i-1])/2,mid={x:a.x+v.x*t,y:a.y+v.y*t};
      const n={x:-v.y/size*.001,y:v.x/size*.001};
      if(!occupied({x:mid.x+n.x,y:mid.y+n.y})||occupied({x:mid.x-n.x,y:mid.y-n.y}))continue;
      const p={x:a.x+v.x*cuts[i-1],y:a.y+v.y*cuts[i-1]},q={x:a.x+v.x*cuts[i],y:a.y+v.y*cuts[i]};
      boundary.set(`${key(p)}>${key(q)}`,{a:p,b:q});
    }
  }
  const pieces=[...boundary.values()],outgoing=new Map();
  pieces.forEach((e,i)=>{const k=key(e.a);if(!outgoing.has(k))outgoing.set(k,[]);outgoing.get(k).push(i);});
  const visited=new Set(),contours=[];
  for(let start=0;start<pieces.length;start++) {
    if(visited.has(start))continue;
    const points=[],first=key(pieces[start].a);let index=start,closed=false;
    while(index!==undefined&&!visited.has(index)) {
      visited.add(index);const edge=pieces[index];points.push(edge.a);
      const end=key(edge.b);
      if(end===first){closed=true;break;}
      const next=(outgoing.get(end)||[]).filter(i=>!visited.has(i));
      if(next.length>1) {
        const angle=Math.atan2(edge.b.y-edge.a.y,edge.b.x-edge.a.x);
        next.sort((i,j)=>{
          const turn=e=>(Math.atan2(e.b.y-e.a.y,e.b.x-e.a.x)-angle+Math.PI*2)%(Math.PI*2);
          return turn(pieces[i])-turn(pieces[j]);
        });
      }
      index=next[0];
    }
    if(closed&&points.length>=3) {
      // Remove only collinear subdivision points from the generated border;
      // all navigation/route vertices and actual ribbon corners are retained.
      let clean=points,changed=true;
      while(changed&&clean.length>3) {
        changed=false;
        clean=clean.filter((p,i)=>{
          const a=clean[(i+clean.length-1)%clean.length],b=clean[(i+1)%clean.length],
            u={x:p.x-a.x,y:p.y-a.y},v={x:b.x-p.x,y:b.y-p.y};
          const redundant=Math.abs(cross(u,v))<epsilon*Math.max(1,Math.hypot(u.x,u.y)+Math.hypot(v.x,v.y))&&u.x*v.x+u.y*v.y>=0;
          if(redundant)changed=true;return !redundant;
        });
      }
      if(clean.length>=3)contours.push(clean);
    }
  }
  return contours;
}

// F2 presentation only, measured in the unmodified source SVG's native
// viewBox (0 0 1122.6667 1588). The existing shared rotation makes native
// y horizontal and native x vertical on screen. These areas reference
// architectural walls; no NAV nodes, NAV edges, or route data generate them.
//
// Upper hallway: room fronts <=352, central room fronts >=392.
// Lower hallway: central fronts <=480; lift fronts 507.826/508.451.
// The two 19-unit necks stop short of those lifts; the other halls are
// 30 units wide. Branches use the open gaps outside the stair rectangles.
const F2_CORRIDOR_REGIONS = [
  {id:"upper-hall", bounds:[357,389,387,1238]},
  {id:"lower-east-neck", bounds:[484,386,503,633]},
  {id:"lower-main", bounds:[484,633,514,1032]},
  {id:"lower-lift3-neck", bounds:[484,1032,503,1086]},
  {id:"lower-west-hall", bounds:[484,1086,514,1187]},
  {id:"east-return", bounds:[383,386,504,407]},
  // Parallel architectural diagonal, between the courtyard end (y1163)
  // and Room 227's upper wall (approximately y1238); no circular junction.
  {id:"west-turn", points:[[357,1215],[368,1235],[508,1184],[497,1164]]},
  // The two cross-passages indicated in the guide, between central blocks.
  {id:"central-west-crossing", bounds:[383,870,488,899]},
  {id:"central-east-crossing", bounds:[383,750,488,791]},
  // Room 240 front y995.780 / Stair 1 outer edge y953.387.
  {id:"stair1-branch", bounds:[500,960,697,984]},
  // Room 237 front y665.668 / Stair 2 outer edge y709.292.
  {id:"stair2-branch", bounds:[500,678,697,702]},
  // Small doorway thresholds reach at most two units into facility outlines.
  // Existing facility outlines and fills stay above the corridor overlay.
  {id:"lift1-access", bounds:[383,426,395.45065,440]},
  {id:"lift2-access", bounds:[500,610,510.45065,624]},
  {id:"lift3-access", bounds:[500,1046,509.82565,1060]},
  {id:"stair1-access", bounds:[564,951.386791,578,964]},
  {id:"stair2-access", bounds:[567,698,581,711.29169]},
  {id:"stair3-access", bounds:[362,375.7,370,394]}
];

function buildF2CorridorSurface(svg) {
  const wallLayer=findLayer(svg,/map[\\s_-]*walls/);
  if(!wallLayer)return;
  const polygons=F2_CORRIDOR_REGIONS.map(region=>{
    const points=region.points||(()=>{
      const [x1,y1,x2,y2]=region.bounds;
      return [[x1,y1],[x2,y1],[x2,y2],[x1,y2]];
    })();
    return points.map(([x,y])=>({x,y}));
  });
  // Merge overlapping rectangles into one fill with an exterior border.
  // This removes internal seams only; navigation geometry is never involved.
  const contours=corridorUnionContours(polygons);
  const group=document.createElementNS(SVG_NS,"g");
  group.id="campusnav-floor-corridors";
  group.setAttribute("aria-hidden","true");
  group.dataset.corridorStyle="measured-architectural-surface";
  group.dataset.surfaceAlgorithm="F2-measured-architectural-regions";
  group.dataset.regionCount=F2_CORRIDOR_REGIONS.length;
  group.dataset.regionBounds=JSON.stringify(F2_CORRIDOR_REGIONS.map((r,i)=>({
    id:r.id,bounds:r.bounds||[
      Math.min(...polygons[i].map(p=>p.x)),Math.min(...polygons[i].map(p=>p.y)),
      Math.max(...polygons[i].map(p=>p.x)),Math.max(...polygons[i].map(p=>p.y))
    ]
  })));
  group.dataset.contours=contours.length;
  const surface=document.createElementNS(SVG_NS,"path");
  surface.setAttribute("d",contours.map(p=>`M ${p.map(v=>`${v.x},${v.y}`).join(" L ")} Z`).join(" "));
  surface.setAttribute("class","cn-corridor-surface");
  group.appendChild(surface);
  svg.insertBefore(group,wallLayer);
}
function hideTechnicalGraph(svg) {
  svg.querySelectorAll("g").forEach(group=>{
    if (/\bnav[\s_-]*(nodes|edges)|navigation[\s_-]*(nodes|edges)/.test(layerToken(group))) {
      group.classList.add("cn-hide-graph");group.setAttribute("aria-hidden","true");
    }
  });
  svg.querySelectorAll("circle,ellipse,text,path,line").forEach(shape=>{
    if(shape.closest(".cn-hide-graph"))return;
    const id=shape.id||"",text=(shape.textContent||"").trim();
    if(/^(nav[-_]|node[-_]|edge[-_]|C\d+$)/i.test(id) ||
      (shape.localName==="text" && /^(C\d+|NAV[-_].*|NODE[-_].*)$/i.test(text)) ||
      (["circle","ellipse"].includes(shape.localName) &&
       /008000|0093ff|1597e5/i.test((shape.getAttribute("style")||"")+(shape.getAttribute("fill")||"")))) {
      shape.classList.add("cn-hide-graph");shape.setAttribute("aria-hidden","true");
    }
  });
}
function isClosedShape(shape) {
  return shape.localName==="rect" || shape.localName==="polygon" ||
    (shape.localName==="path" && /[zZ]\s*$/.test(shape.getAttribute("d")||""));
}
function containsRootPoint(shape,point,svg) {
  if(!isClosedShape(shape)||!point||typeof shape.isPointInFill!=="function")return false;
  const matrix=shape.getCTM()?.inverse().multiply(svg.getCTM());
  return Boolean(matrix && shape.isPointInFill(new DOMPoint(point.x,point.y).matrixTransform(matrix)));
}
function containedShape(label,shapes,svg,anchor=null) {
  const box=label.getBBox();
  const point=anchor||pointInRoot(label,box.x+box.width/2,box.y+box.height/2,svg);
  const candidates=shapes.filter(shape=>containsRootPoint(shape,point,svg));
  return candidates.length===1?candidates[0]:null;
}
function colorInfrastructure(svg,floorId) {
  const layer=findLayer(svg,/map[\s_-]*infrastructure/);if(!layer)return;
  layer.classList.add("cn-infrastructure-outline");
  const shapes=[...layer.querySelectorAll("rect,path,polygon")].filter(isClosedShape);
  const nodes=collectNavNodes(findLayer(svg,/nav[\s_-]*nodes/),floorId,svg);
  layer.querySelectorAll("text").forEach(label=>{
    const match=label.textContent.trim().match(/^(LIFT|STAIRS?)(\d+)/i);if(!match)return;
    const kind=/lift/i.test(match[1])?"lift":"stair",number=match[2];
    const connectorCode=`${kind==="lift"?"LIFT":"STAIRS"}${number}`;
    const node=nodes.find(n=>new RegExp(`^${kind==="lift"?"LIFT":"STAIRS?"}${number}(?:-|$)`,"i").test(n.id));
    const shape=containedShape(label,shapes,svg,node)||containedShape(label,shapes,svg);
    if(shape) {
      shape.classList.add("cn-facility",`cn-space-${kind}`);
      tagConnector(shape,connectorCode);
      if(kind==="stair")addStairDetail(svg,shape,floorId,number);
    }
    label.textContent=`${kind==="lift"?"Lift":"Stair"} ${number}`;
    label.classList.add("cn-facility-label",`cn-label-${kind}`);
    tagConnector(label,connectorCode);
  });
  // Older maps have closed facility outlines without printed facility labels.
  // An explicitly identified connector inside exactly one existing outline
  // can label and color that outline without inventing room geometry.
  const labeled = new Set([...layer.querySelectorAll("text")].map(label=>label.textContent.trim()));
  for (const node of nodes) {
    const match=node.id.match(/^(LIFT|STAIRS?)(\d+)(?:-|$)/i);
    if (!match) continue;
    const kind=/lift/i.test(match[1])?"lift":"stair";
    const name=`${kind==="lift"?"Lift":"Stair"} ${match[2]}`;
    const connectorCode=`${kind==="lift"?"LIFT":"STAIRS"}${match[2]}`;
    if (labeled.has(name)) continue;
    const candidates=shapes.filter(shape=>containsRootPoint(shape,node,svg));
    if (candidates.length!==1) continue;
    const shape=candidates[0];
    shape.classList.add("cn-facility",`cn-space-${kind}`);
    tagConnector(shape,connectorCode);
    if(kind==="stair")addStairDetail(svg,shape,floorId,match[2]);
    const b=shape.getBBox(),p=pointInRoot(shape,b.x+b.width/2,b.y+b.height/2,svg);
    const label=document.createElementNS(SVG_NS,"text");
    const local=new DOMPoint(p.x,p.y).matrixTransform(layer.getCTM().inverse().multiply(svg.getCTM()));
    label.setAttribute("x",local.x); label.setAttribute("y",local.y);
    label.setAttribute("text-anchor","middle");
    label.style.fontSize=`${Math.min(getViewBox(svg).w,getViewBox(svg).h)*.008}px`;
    label.classList.add("cn-facility-label",`cn-label-${kind}`);
    tagConnector(label,connectorCode);
    label.textContent=name; layer.appendChild(label); labeled.add(name);
  }
}

function addStairDetail(svg,shape,floorId,number) {
  const detailId=`cn-stair-detail-${floorId}-${number}`;
  if(svg.querySelector(`#${detailId}`))return;
  let defs=svg.querySelector("defs");
  if(!defs){defs=document.createElementNS(SVG_NS,"defs");svg.insertBefore(defs,svg.firstChild);}
  const clipId=`cn-stair-clip-${floorId}-${number}`;
  const clip=document.createElementNS(SVG_NS,"clipPath");
  clip.id=clipId;clip.setAttribute("clipPathUnits","userSpaceOnUse");
  const mask=shape.cloneNode(true);mask.removeAttribute("id");mask.removeAttribute("class");mask.removeAttribute("style");
  mask.setAttribute("fill","#fff");mask.setAttribute("stroke","none");clip.appendChild(mask);defs.appendChild(clip);

  const box=shape.getBBox(),horizontal=box.width>=box.height;
  const group=document.createElementNS(SVG_NS,"g");group.id=detailId;
  group.setAttribute("class","cn-stair-detail");group.setAttribute("clip-path",`url(#${clipId})`);
  const steps=8;
  for(let index=1;index<steps;index+=1){
    const line=document.createElementNS(SVG_NS,"line");line.setAttribute("class","cn-stair-tread");
    if(horizontal){
      const x=box.x+box.width*index/steps;
      line.setAttribute("x1",x);line.setAttribute("x2",x);
      line.setAttribute("y1",box.y);line.setAttribute("y2",box.y+box.height);
    }else{
      const y=box.y+box.height*index/steps;
      line.setAttribute("x1",box.x);line.setAttribute("x2",box.x+box.width);
      line.setAttribute("y1",y);line.setAttribute("y2",y);
    }
    group.appendChild(line);
  }
  const run=document.createElementNS(SVG_NS,"line");run.setAttribute("class","cn-stair-run");
  const arrow=document.createElementNS(SVG_NS,"polygon");arrow.setAttribute("class","cn-stair-arrow");
  if(horizontal){
    const stair3=String(number)==="3";
    const y=box.y+box.height/2,x1=box.x+box.width*(stair3?.8:.2),x2=box.x+box.width*(stair3?.22:.78),s=Math.min(box.height*.16,5);
    run.setAttribute("x1",x1);run.setAttribute("y1",y);run.setAttribute("x2",x2);run.setAttribute("y2",y);
    const tail=stair3?x2+s*1.8:x2-s*1.8;
    arrow.setAttribute("points",`${x2},${y} ${tail},${y-s} ${tail},${y+s}`);
  }else{
    const x=box.x+box.width/2,y1=box.y+box.height*.8,y2=box.y+box.height*.22,s=Math.min(box.width*.16,5);
    run.setAttribute("x1",x);run.setAttribute("y1",y1);run.setAttribute("x2",x);run.setAttribute("y2",y2);
    arrow.setAttribute("points",`${x},${y2} ${x-s},${y2+s*1.8} ${x+s},${y2+s*1.8}`);
  }
  group.appendChild(run);group.appendChild(arrow);shape.parentNode.insertBefore(group,shape.nextSibling);
}
function semanticRoomClass(location) {
  const hay=normalizeText(`${location?.type||""} ${location?.name||""}`);
  if(/toilet|bathroom|washroom|restroom|\bwc\b/.test(hay))return "bathroom";
  if(/research|laboratory|\blab\b/.test(hay))return "lab";
  if(/faculty|office|admin|staff/.test(hay))return "office";
  if(/electrical|utility|store|storage|server|service|mechanical/.test(hay))return "utility";
  if(/courtyard|open area|open.to.sky|break.?out|refuge|garden|atrium/.test(hay))return "courtyard";
  if(/auditorium|seminar/.test(hay))return "auditorium";
  if(/multipurpose|free room|flexible/.test(hay))return "multipurpose";
  if(/classroom|\broom\b|lecture/.test(hay))return "classroom";
  return "unknown";
}
function semanticTypeLabel(kind) {
  return {classroom:"Classroom",lab:"Lab / research",office:"Faculty / office",
    bathroom:"Bathroom",utility:"Utility",courtyard:"Open space",
    auditorium:"Auditorium",multipurpose:"Flexible room"}[kind]||"";
}
function locationKey(code) {
  return String(code).toUpperCase().replace(/^G-(\d+)/,"G$1");
}
function colorRoomLabels(svg,floorId) {
  const layer=findLayer(svg,/map[\s_-]*rooms/);if(!layer)return;
  const locations=new Map((state.locationsByFloor.get(floorId)||[]).map(item=>[locationKey(item.code),item]));
  const shapes=[...layer.querySelectorAll("rect,path,polygon")].filter(isClosedShape),labels=[...layer.querySelectorAll("text")];
  for(const label of labels) {
    const raw=label.textContent.trim();
    const localAnchor=labelLocalAnchor(label),rootAnchor=labelAnchorInRoot(label,svg);
    if(!label.hasAttribute("x"))label.setAttribute("x",localAnchor.x);
    if(!label.hasAttribute("y"))label.setAttribute("y",localAnchor.y);
    const location=locations.get(locationKey(raw))||{name:raw,type:""};
    const kind=semanticRoomClass(location),shape=containedShape(label,shapes,svg,rootAnchor);
    const uniqueShape=shape && labels.filter(other=>{
      const b=other.getBBox();
      return containsRootPoint(shape,pointInRoot(other,b.x+b.width/2,b.y+b.height/2,svg),svg);
    }).length===1 ? shape : null;
    if(uniqueShape)uniqueShape.classList.add("cn-facility",`cn-space-${kind}`);
    label.classList.add("cn-space-label",`cn-label-${kind}`);
    label.setAttribute("aria-label",`${raw} · ${location.name||semanticTypeLabel(kind)}`);
    const title=document.createElementNS(SVG_NS,"tspan");
    title.setAttribute("x",localAnchor.x);title.setAttribute("y",localAnchor.y);
    title.textContent=raw;
    label.replaceChildren(title);
    const type=semanticTypeLabel(kind);
    if(type) {
      const subtitle=document.createElementNS(SVG_NS,"tspan");
      subtitle.setAttribute("x",label.getAttribute("x")||"0");
      subtitle.setAttribute("dy","1.3em");subtitle.setAttribute("class","cn-label-type");
      subtitle.textContent=type;label.appendChild(subtitle);
    }
    if(/^(?:G-?)?\d+(?:-[A-Z])?$/i.test(raw)&&(kind==="classroom"||kind==="bathroom")) {
      addRoomInteriorDetail(svg,layer,label,uniqueShape,kind,raw,rootAnchor);
    }
  }
}

function addRoomInteriorDetail(svg,layer,label,shape,kind,code,rootAnchor=null) {
  const detailId=`cn-room-detail-${svg.dataset.floor}-${String(code).replace(/[^a-z0-9]+/gi,"-")}`;
  if(svg.querySelector(`#${detailId}`))return;
  const size=Math.min(getViewBox(svg).w,getViewBox(svg).h);
  const layerMatrix=layer.getCTM()?.inverse().multiply(svg.getCTM());
  const local=rootAnchor&&layerMatrix
    ? new DOMPoint(rootAnchor.x,rootAnchor.y).matrixTransform(layerMatrix)
    : labelLocalAnchor(label);
  const x=local.x,y=local.y;
  const w=size*(kind==="classroom"?.047:.036),h=size*(kind==="classroom"?.035:.032);
  const group=document.createElementNS(SVG_NS,"g");
  group.id=detailId;group.setAttribute("class",`cn-room-detail cn-${kind}-detail`);
  group.dataset.roomCode=code;group.setAttribute("aria-hidden","true");
  if(shape) {
    let defs=svg.querySelector("defs");
    if(!defs){defs=document.createElementNS(SVG_NS,"defs");svg.insertBefore(defs,svg.firstChild);}
    const clipId=`${detailId}-clip`,clip=document.createElementNS(SVG_NS,"clipPath");
    clip.id=clipId;clip.setAttribute("clipPathUnits","userSpaceOnUse");
    const mask=shape.cloneNode(true);mask.removeAttribute("id");mask.removeAttribute("class");mask.removeAttribute("style");
    mask.setAttribute("fill","#fff");mask.setAttribute("stroke","none");clip.appendChild(mask);defs.appendChild(clip);
    group.setAttribute("clip-path",`url(#${clipId})`);
  }

  if(kind==="classroom") {
    const board=document.createElementNS(SVG_NS,"rect");
    board.setAttribute("x",x-w*.34);board.setAttribute("y",y-h*.72);
    board.setAttribute("width",w*.68);board.setAttribute("height",h*.16);
    board.setAttribute("rx",h*.025);board.setAttribute("class","cn-classroom-board");group.appendChild(board);
    const ledge=document.createElementNS(SVG_NS,"line");
    ledge.setAttribute("x1",x-w*.38);ledge.setAttribute("y1",y-h*.53);
    ledge.setAttribute("x2",x+w*.38);ledge.setAttribute("y2",y-h*.53);
    ledge.setAttribute("class","cn-classroom-board-ledge");group.appendChild(ledge);
    const deskPositions=[[-.30,-.16],[.30,-.16],[-.30,.42],[.30,.42]];
    for(const [dx,dy] of deskPositions) {
      const desk=document.createElementNS(SVG_NS,"rect");
      desk.setAttribute("x",x+w*dx-w*.105);desk.setAttribute("y",y+h*dy-h*.075);
      desk.setAttribute("width",w*.21);desk.setAttribute("height",h*.15);
      desk.setAttribute("rx",h*.025);desk.setAttribute("class","cn-classroom-desk");group.appendChild(desk);
      const chair=document.createElementNS(SVG_NS,"circle");
      chair.setAttribute("cx",x+w*dx);chair.setAttribute("cy",y+h*dy+h*.15);
      chair.setAttribute("r",h*.055);chair.setAttribute("class","cn-classroom-chair");group.appendChild(chair);
    }
  } else {
    const stall=document.createElementNS(SVG_NS,"path");
    stall.setAttribute("d",`M ${x-w*.44},${y-h*.48} H ${x-w*.06} V ${y+h*.48} H ${x-w*.44} Z`);
    stall.setAttribute("class","cn-bathroom-stall");group.appendChild(stall);
    const tank=document.createElementNS(SVG_NS,"rect");
    tank.setAttribute("x",x-w*.36);tank.setAttribute("y",y-h*.28);
    tank.setAttribute("width",w*.20);tank.setAttribute("height",h*.13);
    tank.setAttribute("rx",h*.025);tank.setAttribute("class","cn-bathroom-fixture");group.appendChild(tank);
    const bowl=document.createElementNS(SVG_NS,"ellipse");
    bowl.setAttribute("cx",x-w*.26);bowl.setAttribute("cy",y-h*.01);
    bowl.setAttribute("rx",w*.12);bowl.setAttribute("ry",h*.14);
    bowl.setAttribute("class","cn-bathroom-fixture");group.appendChild(bowl);
    const sink=document.createElementNS(SVG_NS,"circle");
    sink.setAttribute("cx",x+w*.25);sink.setAttribute("cy",y-h*.18);
    sink.setAttribute("r",h*.12);sink.setAttribute("class","cn-bathroom-sink");group.appendChild(sink);
    const faucet=document.createElementNS(SVG_NS,"path");
    faucet.setAttribute("d",`M ${x+w*.25},${y-h*.34} v ${h*.10} h ${w*.07}`);
    faucet.setAttribute("class","cn-bathroom-faucet");group.appendChild(faucet);
    const drain=document.createElementNS(SVG_NS,"circle");
    drain.setAttribute("cx",x+w*.25);drain.setAttribute("cy",y-h*.18);
    drain.setAttribute("r",h*.025);drain.setAttribute("class","cn-bathroom-drain");group.appendChild(drain);
    const sign=document.createElementNS(SVG_NS,"g");
    sign.setAttribute("class","cn-bathroom-symbol");sign.dataset.roomCode=code;
    const badge=document.createElementNS(SVG_NS,"rect");
    badge.setAttribute("x",x+w*.07);badge.setAttribute("y",y+h*.08);
    badge.setAttribute("width",w*.38);badge.setAttribute("height",h*.38);
    badge.setAttribute("rx",h*.07);badge.setAttribute("class","cn-bathroom-sign-bg");sign.appendChild(badge);
    for(const offset of [.17,.34]) {
      const head=document.createElementNS(SVG_NS,"circle");
      head.setAttribute("cx",x+w*offset);head.setAttribute("cy",y+h*.17);
      head.setAttribute("r",h*.043);head.setAttribute("class","cn-bathroom-sign-person");sign.appendChild(head);
      const body=document.createElementNS(SVG_NS,"path");
      body.setAttribute("d",`M ${x+w*(offset-.055)},${y+h*.24} h ${w*.11} l ${w*.035},${h*.13} h ${-w*.07} v ${h*.07} h ${-w*.075} v ${-h*.07} h ${-w*.07} Z`);
      body.setAttribute("class","cn-bathroom-sign-person");sign.appendChild(body);
    }
    group.appendChild(sign);
  }
  layer.insertBefore(group,label);
}
function raiseMapLabels(svg) {
  const group=document.createElementNS(SVG_NS,"g");group.id="campusnav-map-labels";
  for(const layer of svg.querySelectorAll("g")) {
    if(!/map[\s_-]*(rooms|infrastructure|open[\s_-]*spaces?|access)/.test(layerToken(layer)))continue;
    for(const label of [...layer.querySelectorAll("text")]) {
      const clone=label.cloneNode(true);clone.removeAttribute("id");
      clone.dataset.mapLabel="true";
      clone.dataset.sourceFont=String(parseFloat(getComputedStyle(label).fontSize)||12);
      const anchor=labelAnchorInRoot(label,svg);
      if(!anchor)continue;
      clone.removeAttribute("transform");
      clone.setAttribute("x",anchor.x);clone.setAttribute("y",anchor.y);
      clone.querySelectorAll("tspan").forEach(span=>{
        span.setAttribute("x",anchor.x);
        if(span.hasAttribute("y"))span.setAttribute("y",anchor.y);
      });
      group.appendChild(clone);
      label.classList.add("cn-source-label");label.setAttribute("aria-hidden","true");
    }
  }
  group.setAttribute("pointer-events","none");svg.appendChild(group);
}
function mapContentViewBox(svg,fallback) {
  const wall=findLayer(svg,/map[\s_-]*walls/);if(!wall)return fallback;
  const b=wall.getBBox(),m=svg.getCTM().inverse().multiply(wall.getCTM());
  const corners=[[b.x,b.y],[b.x+b.width,b.y],[b.x,b.y+b.height],[b.x+b.width,b.y+b.height]]
    .map(([x,y])=>new DOMPoint(x,y).matrixTransform(m));
  const xs=corners.map(p=>p.x),ys=corners.map(p=>p.y),x=Math.min(...xs),y=Math.min(...ys);
  const w=Math.max(...xs)-x,h=Math.max(...ys)-y,pad=Math.max(w,h)*.025;
  return {x:x-pad,y:y-pad,w:w+pad*2,h:h+pad*2};
}

function drawRouteOverlay() {
  const svg = state.currentSvg;
  if (!svg) return;
  svg.querySelector("#campusnav-route-overlay")?.remove();
  if (!state.route) return;

  const floor = state.selectedFloor;
  const allPoints = state.floorRouteIndexes[floor] || [];
  if (!allPoints.length) return;

  const currentCheckpoint = state.route.checkpoints?.[state.currentCheckpointIndex];
  const currentPathIndex = currentCheckpoint?.path_index ?? 0;
  const remaining = allPoints.filter((point) => point.globalIndex === -1 || point.globalIndex >= currentPathIndex);
  if (!remaining.length) return;
  const displayPoints = remaining.map(point => ({
    ...point,
    ...sourcePointToDisplay(point.x, point.y),
  }));

  // Every point is retained, including tiny bends and repeated coordinates.
  const group=document.createElementNS(SVG_NS,"g");
  group.id="campusnav-route-overlay";
  if(displayPoints.length>=2) {
    const points=displayPoints.map(p=>`${p.x},${p.y}`).join(" ");
    for(const cls of ["cn-route-halo","cn-route-line"]) {
      const line=document.createElementNS(SVG_NS,"polyline");
      line.setAttribute("points",points);
      line.setAttribute("class",cls+(cls==="cn-route-line"&&state.animateRouteDraw?" cn-route-animate":""));
      line.setAttribute("pointer-events","none");group.appendChild(line);
    }
  } else {
    // Pass-through floor: the backend route touches this floor at a single
    // connector node, so there is no polyline to draw. Without an explicit
    // callout the map would show no route information at all here.
    drawConnectorCallout(group,displayPoints[0],floor);
  }
  state.animateRouteDraw=false;
  const arrows=document.createElementNS(SVG_NS,"g");
  arrows.id="campusnav-route-arrows";group.appendChild(arrows);

  const markers=document.createElementNS(SVG_NS,"g");
  markers.id="campusnav-route-markers";group.appendChild(markers);
  markers.addEventListener("pointerdown",event=>{
    if(event.target.closest?.("[data-checkpoint-index]"))event.stopPropagation();
  });
  markers.addEventListener("click",event=>{
    const target=event.target.closest?.("[data-checkpoint-index]");
    if(!target)return;
    event.stopPropagation();
    reachCheckpoint(Number(target.dataset.checkpointIndex));
  });
  markers.addEventListener("keydown",event=>{
    if(event.key!=="Enter"&&event.key!==" ")return;
    const target=event.target.closest?.("[data-checkpoint-index]");
    if(!target)return;
    event.preventDefault();event.stopPropagation();
    reachCheckpoint(Number(target.dataset.checkpointIndex));
  });

  const labels=svg.querySelector("#campusnav-map-labels");
  svg.insertBefore(group,labels||null);
  updateOverlayScale();
}

function connectorCalloutText(floor) {
  // Describe the SAME next action the dock describes, so the map and the
  // dock can never disagree about what the user should do here.
  const checkpoints = state.route?.checkpoints || [];
  const next = checkpoints[state.currentCheckpointIndex + 1];
  if (!next) return { detail: "Destination reached" };
  if (next.floor_id === floor) {
    return { detail: `Point ${next.checkpoint} · tap when you arrive` };
  }
  return { detail: `Continue to ${navigationFloorName(next.floor_id)}` };
}

function drawConnectorCallout(group, point, floor) {
  if (!point) return;
  // No remaining checkpoint means the user has arrived; the arrival marker
  // already communicates that, so a callout here would only duplicate it.
  if (!state.route?.checkpoints?.[state.currentCheckpointIndex + 1]) return;
  const units = getUnitsPerPixel();
  const { detail } = connectorCalloutText(floor);

  // Rings only. The tappable node itself is rendered by drawRouteMarkers from
  // the real backend checkpoint, so drawing another dot here would both
  // duplicate it and cover the tap target.
  for (const [radiusPx, cls] of [[26, "cn-connector-callout-ring"], [15, "cn-next-pulse"]]) {
    const ring = document.createElementNS(SVG_NS, "circle");
    ring.setAttribute("cx", point.x);
    ring.setAttribute("cy", point.y);
    ring.setAttribute("class", cls);
    ring.dataset.radiusPx = String(radiusPx);
    ring.setAttribute("r", radiusPx * units);
    ring.setAttribute("pointer-events", "none");
    group.appendChild(ring);
  }

  if (!detail) return;
  const label = document.createElementNS(SVG_NS, "text");
  label.setAttribute("x", point.x);
  label.setAttribute("y", point.y);
  label.setAttribute("class", "cn-connector-callout-label");
  label.dataset.fontPx = "11";
  label.dataset.offsetXPx = "0";
  label.dataset.offsetYPx = "-26";
  label.dataset.anchorX = String(point.x);
  label.dataset.anchorY = String(point.y);
  label.textContent = detail;
  group.appendChild(label);
}

function drawDirectionArrows(group, points, visibleMarkers=[]) {
  if (points.length < 2) return;
  if(state.selectedFloor==="F2") {
    const units=getUnitsPerPixel(),length=7*units,width=5*units,spacing=105*units;
    let travelled=0,next=spacing*.55;
    for(let i=0;i<points.length-1;i++) {
      const a=points[i],b=points[i+1],dx=b.x-a.x,dy=b.y-a.y,segment=Math.hypot(dx,dy);
      if(segment<.001)continue;
      const ux=dx/segment,uy=dy/segment;
      while(next<=travelled+segment) {
        const position=next-travelled;next+=spacing;
        // Keep each complete arrow on a single segment, away from bends and
        // visible markers. Its symmetry axis lies exactly on that segment.
        if(position<14*units||segment-position<14*units)continue;
        const x=a.x+ux*position,y=a.y+uy*position;
        if(visibleMarkers.some(p=>Math.hypot(p.x-x,p.y-y)<16*units))continue;
        const tip={x:x+ux*length*.7,y:y+uy*length*.7};
        const base={x:x-ux*length*.55,y:y-uy*length*.55};
        const arrow=document.createElementNS(SVG_NS,"polygon");
        arrow.setAttribute("points",`${tip.x},${tip.y} ${base.x-uy*width/2},${base.y+ux*width/2} ${base.x+uy*width/2},${base.y-ux*width/2}`);
        arrow.setAttribute("class","cn-route-arrowhead");
        arrow.dataset.centerX=x;arrow.dataset.centerY=y;arrow.dataset.segmentIndex=i;
        group.appendChild(arrow);
      }
      travelled+=segment;
    }
    // At a compact full-floor view the regularly spaced candidates can all
    // land near bends. Use one eligible segment midpoint as a clean fallback.
    if(!group.childElementCount) {
      const segments=points.slice(0,-1).map((a,i)=>({a,b:points[i+1],i,
        size:Math.hypot(points[i+1].x-a.x,points[i+1].y-a.y)})).sort((a,b)=>b.size-a.size);
      for(const {a,b,i,size}of segments) {
        if(size<32*units)continue;
        const x=(a.x+b.x)/2,y=(a.y+b.y)/2;
        if(visibleMarkers.some(p=>Math.hypot(p.x-x,p.y-y)<16*units))continue;
        const ux=(b.x-a.x)/size,uy=(b.y-a.y)/size;
        const tip={x:x+ux*length*.7,y:y+uy*length*.7},base={x:x-ux*length*.55,y:y-uy*length*.55};
        const arrow=document.createElementNS(SVG_NS,"polygon");
        arrow.setAttribute("points",`${tip.x},${tip.y} ${base.x-uy*width/2},${base.y+ux*width/2} ${base.x+uy*width/2},${base.y-ux*width/2}`);
        arrow.setAttribute("class","cn-route-arrowhead");
        arrow.dataset.centerX=x;arrow.dataset.centerY=y;arrow.dataset.segmentIndex=i;
        group.appendChild(arrow);break;
      }
    }
    return;
  }

  // Draw explicit SVG triangles rather than relying only on marker-end.
  // This stays visible in imported Inkscape SVGs and after the shared
  // 90° clockwise transform.
  const unitsPerPx = getUnitsPerPixel();
  const desiredSpacing = 105 * unitsPerPx;
  const arrowLength = 7 * unitsPerPx;
  const arrowWidth = 5 * unitsPerPx;
  let distanceSinceArrow = desiredSpacing * 0.45;

  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i];
    const b = points[i + 1];
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const segment = Math.hypot(dx, dy);
    if (segment <= 0.001) continue;

    const ux = dx / segment;
    const uy = dy / segment;
    let position = Math.max(0, desiredSpacing - distanceSinceArrow);

    while (position < segment - arrowLength * 1.3) {
      const cx = a.x + ux * position;
      const cy = a.y + uy * position;
      const tipX = cx + ux * arrowLength * 0.7;
      const tipY = cy + uy * arrowLength * 0.7;
      const baseX = cx - ux * arrowLength * 0.55;
      const baseY = cy - uy * arrowLength * 0.55;
      const px = -uy * arrowWidth * 0.5;
      const py = ux * arrowWidth * 0.5;

      const arrow = document.createElementNS(SVG_NS, "polygon");
      arrow.setAttribute(
        "points",
        `${tipX},${tipY} ${baseX + px},${baseY + py} ${baseX - px},${baseY - py}`
      );
      arrow.setAttribute("class", "cn-route-arrowhead");
      group.appendChild(arrow);

      position += desiredSpacing;
    }

    distanceSinceArrow = segment - Math.max(0, position - desiredSpacing);
    if (distanceSinceArrow > desiredSpacing) distanceSinceArrow %= desiredSpacing;
  }
}

function drawCheckpoint(group, cp, index) {
  const isCurrent = index === state.currentCheckpointIndex;
  const isNext = index === state.currentCheckpointIndex + 1;
  const isDestination = index === state.route.checkpoints.length - 1;

  if (isCurrent) {
    const halo = document.createElementNS(SVG_NS, "circle");
    halo.setAttribute("cx", cp.x);
    halo.setAttribute("cy", cp.y);
    halo.setAttribute("class", "cn-position-halo");
    halo.dataset.radiusPx = "18";
    group.appendChild(halo);

    // One-shot completion flash for the point the user just confirmed.
    if (state.justCompletedIndex === index) {
      const burst = document.createElementNS(SVG_NS, "circle");
      burst.setAttribute("cx", cp.x);
      burst.setAttribute("cy", cp.y);
      burst.setAttribute("class", "cn-complete-burst");
      burst.dataset.radiusPx = "12";
      group.appendChild(burst);
    }
  }

  // The NEXT node carries two offset breathing rings so it is the single
  // most obvious thing on the map at a glance.
  if (isNext) {
    for (const cls of ["cn-next-pulse", "cn-next-pulse ring-2"]) {
      const ring = document.createElementNS(SVG_NS, "circle");
      ring.setAttribute("cx", cp.x);
      ring.setAttribute("cy", cp.y);
      ring.setAttribute("class", cls);
      ring.dataset.radiusPx = "11";
      group.appendChild(ring);
    }
  }

  const hit = document.createElementNS(SVG_NS, "circle");
  hit.setAttribute("cx", cp.x);
  hit.setAttribute("cy", cp.y);
  hit.setAttribute("class", "cn-checkpoint-hit");
  hit.dataset.radiusPx = "17";
  hit.dataset.checkpointIndex = String(index);

  const circle = document.createElementNS(SVG_NS, "circle");
  circle.setAttribute("cx", cp.x);
  circle.setAttribute("cy", cp.y);
  circle.dataset.radiusPx = state.selectedFloor==="F2"
    ? (isCurrent?"8":isDestination?"7":"4.5")
    : (isCurrent ? "9" : isDestination ? "8" : "5.5");
  circle.setAttribute("role","button");
  circle.setAttribute("tabindex","0");
  circle.setAttribute("aria-label",`Point ${cp.checkpoint}: ${friendlyCode(cp.label)}`);
  circle.dataset.checkpointIndex = String(index);
  // Standing ON the destination is its own state: it must not collapse into
  // the generic "current position" marker, or arrival reads as mid-route.
  const arrived = isCurrent && isDestination;
  const baseClass = arrived
    ? "cn-checkpoint-destination cn-checkpoint-arrived"
    : isCurrent
      ? "cn-checkpoint-current"
      : isDestination
        ? "cn-checkpoint-destination"
        : "cn-checkpoint-dot";
  circle.setAttribute(
    "class",
    `${baseClass}${isNext ? " cn-checkpoint-next" : ""}${cp.is_turn ? " cn-checkpoint-turn" : ""}${index === 0 ? " cn-route-start" : ""}`
  );
  group.appendChild(circle);

  const number = document.createElementNS(SVG_NS, "text");
  number.setAttribute("x", cp.x);
  number.setAttribute("y", cp.y);
  number.dataset.fontPx = "6.5";
  number.setAttribute(
    "class",
    `cn-checkpoint-number${isCurrent ? " current" : ""}${isNext ? " next" : ""}${isDestination ? " destination" : ""}`
  );
  number.textContent = String(cp.checkpoint);
  group.appendChild(number);

  if (isCurrent) {
    const label = document.createElementNS(SVG_NS, "text");
    label.setAttribute("x", cp.x);
    label.setAttribute("y", cp.y);
    label.dataset.fontPx = "10";
    label.dataset.offsetXPx = "13";
    label.dataset.offsetYPx = "-12";
    label.dataset.anchorX = String(cp.x);
    label.dataset.anchorY = String(cp.y);
    label.setAttribute("class", `cn-location-label${arrived ? " cn-destination-label" : ""}`);
    label.textContent = arrived ? "✓ Arrived" : "You are here";
    group.appendChild(label);
  }
  if (isDestination && !isCurrent) {
    const label = document.createElementNS(SVG_NS, "text");
    label.setAttribute("x", cp.x);
    label.setAttribute("y", cp.y);
    label.dataset.fontPx = "10";
    label.dataset.offsetXPx = "13";
    label.dataset.offsetYPx = "15";
    label.dataset.anchorX = String(cp.x);
    label.dataset.anchorY = String(cp.y);
    label.setAttribute("class", "cn-location-label cn-destination-label");
    label.textContent = navigationPlaceLabel(cp.label);
    group.appendChild(label);
  }
  group.appendChild(hit);
}

function drawRouteMarkers(group,points,units) {
  const checkpoints=state.route?.checkpoints||[],candidates=new Map();
  const current=checkpoints[state.currentCheckpointIndex]?.path_index??0;
  const byIndex=new Map(points.map(p=>[p.globalIndex,p]));
  const checkpointByPathIndex=new Map(checkpoints.map((cp,index)=>[cp.path_index,{cp,index}]));
  for(let index=0;index<checkpoints.length;index++) {
    const cp=checkpoints[index];
    if(cp.floor_id!==state.selectedFloor||cp.path_index<current)continue;
    const essential=index===state.currentCheckpointIndex||index===state.currentCheckpointIndex+1||index===checkpoints.length-1;
    if(!essential)continue;
    const vertex=byIndex.get(cp.path_index);
    if(!vertex)continue;
    // Markers and polyline consume the very same original route vertex.
    const priority=index===state.currentCheckpointIndex?1000:index===state.currentCheckpointIndex+1?950:900;
    candidates.set(vertex.globalIndex,{...vertex,cp,index,priority,essential:true});
  }
  for(let i=1;i<points.length-1;i++) {
    const p=points[i];let before=i-1,after=i+1;
    while(before>=0&&Math.hypot(points[before].x-p.x,points[before].y-p.y)<.001)before--;
    while(after<points.length&&Math.hypot(points[after].x-p.x,points[after].y-p.y)<.001)after++;
    if(before<0||after>=points.length)continue;
    const a=points[before],b=points[after],ux=p.x-a.x,uy=p.y-a.y,vx=b.x-p.x,vy=b.y-p.y;
    const angle=Math.acos(Math.max(-1,Math.min(1,(ux*vx+uy*vy)/(Math.hypot(ux,uy)*Math.hypot(vx,vy)))))*180/Math.PI;
    if(angle<35)continue;
    const candidate=candidates.get(p.globalIndex)||{...p};
    const checkpoint=checkpointByPathIndex.get(p.globalIndex);
    if(checkpoint&&checkpoint.index>=state.currentCheckpointIndex) {
      candidate.cp=checkpoint.cp;
      candidate.index=checkpoint.index;
      candidate.essential=true;
    }
    candidate.turn=true;candidate.priority=Math.max(candidate.priority||0,600+angle);
    candidates.set(p.globalIndex,candidate);
  }
  const displayed=[],spacing=30*units;
  for(const candidate of [...candidates.values()].sort((a,b)=>b.priority-a.priority||a.globalIndex-b.globalIndex)) {
    const minimum=candidate.essential?10*units:spacing;
    if(!candidate.essential&&displayed.some(p=>Math.hypot(p.x-candidate.x,p.y-candidate.y)<minimum))continue;
    displayed.push(candidate);
  }
  const focused=document.activeElement?.dataset?.checkpointIndex;
  group.replaceChildren();group.dataset.minimumSpacingPx="30";
  for(const marker of displayed.sort((a,b)=>a.globalIndex-b.globalIndex)) {
    if(marker.cp) {
      drawCheckpoint(group,{...marker.cp,x:marker.x,y:marker.y},marker.index);
      const circle=group.querySelector(`circle[data-checkpoint-index="${marker.index}"]:not(.cn-checkpoint-hit)`);
      group.querySelectorAll(`[data-checkpoint-index="${marker.index}"]`).forEach(element=>element.dataset.routeIndex=marker.globalIndex);
      if(marker.turn&&circle)circle.dataset.turn="true";
    } else {
      const dot=document.createElementNS(SVG_NS,"circle");
      dot.setAttribute("cx",marker.x);dot.setAttribute("cy",marker.y);
      dot.setAttribute("class","cn-route-turn");dot.setAttribute("aria-hidden","true");
      dot.dataset.radiusPx="4";dot.dataset.routeIndex=marker.globalIndex;dot.dataset.turn="true";
      group.appendChild(dot);
    }
  }
  if(focused!==undefined)group.querySelector(`circle[role="button"][data-checkpoint-index="${focused}"]`)?.focus({preventScroll:true});
  return displayed;
}

function updateOverlayScale() {
  const svg = state.currentSvg;
  if (!svg) return;
  const unitsPerPx = getUnitsPerPixel();
  const current=state.route?.checkpoints?.[state.currentCheckpointIndex]?.path_index??0;
  const points=(state.floorRouteIndexes[state.selectedFloor]||[])
    .filter(p=>p.globalIndex===-1||p.globalIndex>=current)
    .map(point=>({...point,...sourcePointToDisplay(point.x,point.y)}));
  const markers=svg.querySelector("#campusnav-route-markers");
  const displayed=markers ? drawRouteMarkers(markers,points,unitsPerPx):[];

  svg.querySelectorAll("#campusnav-route-overlay circle[data-radius-px]").forEach((circle) => {
    circle.setAttribute("r", Number(circle.dataset.radiusPx) * unitsPerPx);
  });
  svg.querySelectorAll("#campusnav-route-overlay text[data-font-px]").forEach((text) => {
    text.setAttribute("font-size", Number(text.dataset.fontPx) * unitsPerPx);
    if (text.dataset.anchorX) {
      const x = Number(text.dataset.anchorX) + Number(text.dataset.offsetXPx || 0) * unitsPerPx;
      const y = Number(text.dataset.anchorY) + Number(text.dataset.offsetYPx || 0) * unitsPerPx;
      text.setAttribute("x", x);
      text.setAttribute("y", y);
    }
  });
  svg.querySelectorAll("[data-map-label]").forEach(label=>{
    const m=label.getScreenCTM();
    const scale=m?Math.hypot(m.a,m.b):0;
    if(!scale)return;
    const original=Number(label.dataset.sourceFont);
    const compactRoute=document.body.classList.contains("route-active") && matchMedia("(max-width:680px)").matches;
    const px=Math.max(compactRoute?11:9,Math.min(compactRoute?16:13,original*scale));
    label.style.setProperty("font-size",`${px/scale}px`,"important");
  });
  resolveMapLabelCollisions(svg);
  const arrows=svg.querySelector("#campusnav-route-arrows");
  if(arrows) {
    arrows.replaceChildren();
    drawDirectionArrows(arrows,points,displayed);
  }
}

function resolveMapLabelCollisions(svg) {
  const labels=[...svg.querySelectorAll("[data-map-label]")];
  if(!labels.length)return;
  labels.forEach(label=>{
    label.style.visibility="visible";
    label.removeAttribute("aria-hidden");
  });

  const priority=label=>{
    let value=label.classList.contains("cn-facility-label")?300:100;
    if(label.classList.contains("cn-entrance-label"))value=460;
    if(label.classList.contains("cn-open-space-label"))value=260;
    if(label.dataset.connectorCode)value+=120;
    if(label.classList.contains("cn-label-bathroom"))value+=80;
    if(label.classList.contains("cn-label-unknown"))value-=20;
    return value;
  };
  const occupied=[];
  for(const label of labels.sort((a,b)=>priority(b)-priority(a))) {
    const rect=label.getBoundingClientRect();
    if(!rect.width||!rect.height)continue;
    const box={left:rect.left-3,right:rect.right+3,top:rect.top-2,bottom:rect.bottom+2};
    const overlaps=occupied.some(other=>
      box.left<other.right&&box.right>other.left&&box.top<other.bottom&&box.bottom>other.top
    );
    if(overlaps) {
      label.style.visibility="hidden";
      label.setAttribute("aria-hidden","true");
    } else {
      occupied.push(box);
    }
  }
}

function getUnitsPerPixel() {
  if (!state.currentSvg || !state.viewBox) return 1;
  const rect = state.currentSvg.getBoundingClientRect();
  if (!rect.width || !rect.height) return 1;
  return Math.max(state.viewBox.w / rect.width, state.viewBox.h / rect.height);
}

function getViewBox(svg) {
  const raw = svg.getAttribute("viewBox");
  if (raw) {
    const values = raw.trim().split(/[\s,]+/).map(Number);
    if (values.length === 4 && values.every(Number.isFinite)) {
      return { x: values[0], y: values[1], w: values[2], h: values[3] };
    }
  }
  const width = Number(svg.getAttribute("width")) || 1000;
  const height = Number(svg.getAttribute("height")) || 1400;
  return { x: 0, y: 0, w: width, h: height };
}

function applyViewBox() {
  if (!state.currentSvg || !state.viewBox) return;
  const v = state.viewBox;
  state.currentSvg.setAttribute("viewBox", `${v.x} ${v.y} ${v.w} ${v.h}`);
  requestAnimationFrame(updateOverlayScale);
}

function fitMap() {
  if (!state.originalViewBox) return;
  state.viewBox = { ...state.originalViewBox };
  applyViewBox();
}

function zoomMap(factor,clientX=null,clientY=null) {
  if(!state.viewBox||!state.originalViewBox||!state.currentSvg)return;
  const svg=state.currentSvg,v=state.viewBox;
  const point=clientX==null?{x:v.x+v.w/2,y:v.y+v.h/2}:
    new DOMPoint(clientX,clientY).matrixTransform(svg.getScreenCTM().inverse());
  const px=(point.x-v.x)/v.w,py=(point.y-v.y)/v.h,w=v.w*factor,h=v.h*factor;
  if(w<state.originalViewBox.w/7||w>state.originalViewBox.w*1.4)return;
  state.viewBox={x:point.x-px*w,y:point.y-py*h,w,h};applyViewBox();
}
function focusRemainingRoute(cp) {
  if(!cp||!state.originalViewBox)return;
  const base=state.originalViewBox;
  const current=state.route?.checkpoints?.[state.currentCheckpointIndex]?.path_index??0;
  const points=(state.floorRouteIndexes[state.selectedFloor]||[]).filter(p=>p.globalIndex>=current);
  const anchor=sourcePointToDisplay(cp.x,cp.y);
  const following=points
    .filter(p=>p.globalIndex>=cp.path_index)
    .slice(0,6)
    .map(p=>sourcePointToDisplay(p.x,p.y));
  const xs=[anchor.x,...following.map(p=>p.x)];
  const ys=[anchor.y,...following.map(p=>p.y)];
  const spanX=Math.max(...xs)-Math.min(...xs);
  const spanY=Math.max(...ys)-Math.min(...ys);

  // A pass-through floor has a single point and therefore zero span. Zooming
  // to "zero span" used to leave the user staring at an empty corridor, so
  // fall back to a readable neighbourhood around the connector instead.
  const minW=spanX<1&&spanY<1 ? base.w/2.2 : base.w/3.2;
  const minH=spanX<1&&spanY<1 ? base.h/2.2 : base.h/3.2;
  const w=Math.min(base.w,Math.max(minW,spanX*1.7));
  const h=Math.min(base.h,Math.max(minH,spanY*1.7));
  const cx=(Math.min(...xs)+Math.max(...xs))/2;
  const cy=(Math.min(...ys)+Math.max(...ys))/2;
  state.viewBox={x:cx-w/2,y:cy-h/2+h*routeFramingBias(),w,h};
  applyViewBox();
}

function routeFramingBias() {
  // The navigation dock floats over the lower part of the map. Centring a
  // route on the geometric centre would push it underneath that card, so
  // bias the viewport downward (which moves content visually upward).
  const viewport = els.mapViewport?.getBoundingClientRect();
  const dock = els.stepBar && !els.stepBar.hidden ? els.stepBar.getBoundingClientRect() : null;
  if (!viewport?.height || !dock?.height) return 0;
  return Math.min(0.24, (dock.height + 24) / viewport.height / 2);
}

function focusRoutePreview() {
  if (!state.originalViewBox) return;
  const base = state.originalViewBox;
  const points = (state.floorRouteIndexes[state.selectedFloor] || [])
    .map(point => sourcePointToDisplay(point.x, point.y));

  // A multi-floor route often touches the shown floor at one or two points
  // only. Fitting the whole floor plan in that case renders the route as an
  // unreadable speck, which was the single biggest orientation problem.
  if (!points.length) { fitMap(); return; }

  const xs = points.map(p => p.x);
  const ys = points.map(p => p.y);
  const spanX = Math.max(...xs) - Math.min(...xs);
  const spanY = Math.max(...ys) - Math.min(...ys);

  const minW = base.w / 2.4;
  const minH = base.h / 2.4;
  const w = Math.min(base.w, Math.max(minW, spanX * 1.55));
  const h = Math.min(base.h, Math.max(minH, spanY * 1.55));
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
  const cy = (Math.min(...ys) + Math.max(...ys)) / 2;

  state.viewBox = {
    x: Math.max(base.x, Math.min(cx - w / 2, base.x + base.w - w)),
    y: cy - h / 2 + h * routeFramingBias(),
    w,
    h,
  };
  applyViewBox();
}

function centerOnCheckpoint(cp) {
  if (!cp || !state.originalViewBox) return;
  const displayPoint = sourcePointToDisplay(cp.x, cp.y);
  const zoom = 2.55;
  const w = state.originalViewBox.w / zoom;
  const h = state.originalViewBox.h / zoom;
  state.viewBox = {
    x: displayPoint.x - w / 2,
    y: displayPoint.y - h / 2 + h * routeFramingBias(),
    w,
    h,
  };
  applyViewBox();
}

function panStart(event) {
  if (!state.currentSvg || !state.viewBox) return;
  if (event.target.closest?.("button, [data-checkpoint-index]")) return;
  state.dragging = true;
  state.dragStart = {
    clientX: event.clientX,
    clientY: event.clientY,
    viewBox: { ...state.viewBox },
  };
  els.mapViewport.setPointerCapture?.(event.pointerId);
}

function panMove(event) {
  if (!state.dragging || !state.dragStart || !state.currentSvg) return;
  const rect = state.currentSvg.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const units=Math.max(state.dragStart.viewBox.w/rect.width,state.dragStart.viewBox.h/rect.height);
  const dx=(event.clientX-state.dragStart.clientX)*units;
  const dy=(event.clientY-state.dragStart.clientY)*units;
  state.viewBox = {
    ...state.dragStart.viewBox,
    x: state.dragStart.viewBox.x - dx,
    y: state.dragStart.viewBox.y - dy,
  };
  applyViewBox();
}

function panEnd(event) {
  state.dragging = false;
  state.dragStart = null;
  if (els.mapViewport.hasPointerCapture?.(event.pointerId)) els.mapViewport.releasePointerCapture(event.pointerId);
}

function openBlockedDialog() {
  els.blockedDialog.querySelectorAll(".blocked-grid input").forEach((input) => {
    input.checked = state.blocked.has(input.value);
  });
  els.blockedDialog.showModal();
}

function routingCodeForCheckpoint(cp) {
  if (!cp) return "";
  const candidates = state.floorRouteIndexes?.[cp.floor_id] || [];
  const match = candidates.find((point) => point.globalIndex === cp.path_index);
  return match?.original_node_id || cp.node_id;
}

async function rerouteFromCurrentCheckpoint() {
  if (!state.route || !state.lastPlan) return;
  const selected = [...els.blockedDialog.querySelectorAll(".blocked-grid input:checked")].map((input) => input.value);
  if (!selected.length) {
    showToast("Choose at least one blocked connector");
    return;
  }
  selected.forEach((item) => state.blocked.add(item));
  renderBlockedStatus();
  const cp = state.route.checkpoints[state.currentCheckpointIndex];
  els.blockedDialog.close();

  await planRoute({
    start: {
      kind: "location",
      floor_id: cp.floor_id,
      code: routingCodeForCheckpoint(cp),
      name: cp.label,
      type: "checkpoint",
    },
    destination: state.lastPlan.destination,
    mode: state.lastPlan.mode,
    blocked: [...state.blocked],
  });
  showToast("Alternate route calculated from your current point");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

boot();
