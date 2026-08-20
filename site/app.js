const state = { incidents: [] };

function byId(id) {
  return document.getElementById(id);
}

function setText(id, value) {
  byId(id).textContent = String(value);
}

function formatTimestamp(value) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  }).format(new Date(value));
}

function createElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function renderCategories(categories) {
  const container = byId("category-list");
  Object.entries(categories).forEach(([name, count]) => {
    container.append(createElement("span", "", `${name} · ${count}`));
  });
}

function renderServices(services) {
  const grid = byId("service-grid");
  services.forEach((service) => {
    const card = createElement("article", "service-card");
    const top = createElement("div", "service-top");
    top.append(createElement("h3", "", service.name));
    top.append(createElement("span", "", `${service.latest_outcome} now`));

    const value = createElement("div", "latency-value", service.latest_latency_ms);
    value.append(createElement("small", "", " ms latest"));
    const label = createElement(
      "div",
      "latency-label",
      `${service.average_latency_ms} ms average across ${service.samples.length} fixtures`,
    );
    const sparkline = createElement("div", "sparkline");
    sparkline.setAttribute("role", "img");
    sparkline.setAttribute("aria-label", `${service.name} latency history`);
    const maxLatency = Math.max(...service.samples.map((sample) => sample.latency_ms));
    service.samples.forEach((sample) => {
      const bar = createElement("span", sample.outcome);
      bar.style.height = `${Math.max(7, (sample.latency_ms / maxLatency) * 100)}%`;
      bar.title = `${sample.latency_ms} ms · ${sample.outcome}`;
      sparkline.append(bar);
    });

    card.append(top, value, label, sparkline);
    grid.append(card);
  });
}

function renderIncidentRows() {
  const severity = byId("severity-filter").value;
  const query = byId("incident-search").value.trim().toLowerCase();
  const rows = state.incidents.filter((incident) => {
    const matchesSeverity = severity === "all" || incident.priority === severity;
    const haystack = `${incident.service} ${incident.failure_category} ${incident.owner} ${incident.summary}`.toLowerCase();
    return matchesSeverity && haystack.includes(query);
  });

  const body = byId("incident-rows");
  body.replaceChildren();
  if (!rows.length) {
    const row = document.createElement("tr");
    const cell = createElement("td", "empty-row", "No incidents match this view.");
    cell.colSpan = 5;
    row.append(cell);
    body.append(row);
  }

  rows.forEach((incident) => {
    const row = document.createElement("tr");
    const priorityCell = document.createElement("td");
    priorityCell.append(createElement("span", `priority ${incident.priority.toLowerCase()}`, incident.priority));

    const signalCell = document.createElement("td");
    signalCell.append(createElement("span", "incident-title", incident.service));
    signalCell.append(createElement("span", "incident-signal", incident.failure_category.replaceAll("_", " ")));

    const ownerCell = createElement("td", "", incident.owner);
    const confidenceCell = createElement("td", "confidence", `${Math.round(incident.confidence * 100)}%`);
    const stateCell = createElement("td", "state", incident.lifecycle_state);
    row.append(priorityCell, signalCell, ownerCell, confidenceCell, stateCell);
    body.append(row);
  });
  setText("queue-count", `${rows.length} of ${state.incidents.length} incidents`);
}

function renderDashboard(data) {
  const { registry, monitoring, incidents, ai_evaluation: ai, provenance } = data;
  setText("brief-registry", registry.api_count);
  setText("brief-targets", monitoring.target_count);
  setText("brief-incidents", incidents.total_count);
  setText("brief-open", incidents.open_count);
  setText("as-of", formatTimestamp(provenance.as_of));

  setText("eligible-percent", registry.eligible_percent);
  setText("eligible-detail", `${registry.eligible_count} of ${registry.api_count} catalog entries`);
  setText("healthy-percent", monitoring.healthy_percent);
  setText("healthy-detail", `${monitoring.healthy_count} of ${monitoring.check_count} observations`);
  setText("coverage-percent", ai.coverage_percent);
  setText("coverage-detail", `at ${ai.operating_threshold} confidence`);
  setText("modeled-cost", ai.modeled_cost_usd);

  setText("coverage-ratio", `${registry.eligible_count} / ${registry.api_count}`);
  byId("coverage-fill").style.width = `${registry.eligible_percent}%`;
  renderCategories(registry.category_counts);

  setText("healthy-count", monitoring.healthy_count);
  setText("degraded-count", monitoring.degraded_count);
  setText("unhealthy-count", monitoring.unhealthy_count);
  setText("donut-center", `${monitoring.healthy_percent}%`);
  const healthyStop = monitoring.healthy_percent;
  const degradedStop = healthyStop + (monitoring.degraded_count / monitoring.check_count) * 100;
  byId("outcome-donut").style.background = `conic-gradient(var(--mint) 0 ${healthyStop}%, var(--amber) ${healthyStop}% ${degradedStop}%, var(--coral) ${degradedStop}% 100%)`;
  byId("outcome-donut").setAttribute(
    "aria-label",
    `${monitoring.healthy_count} healthy, ${monitoring.degraded_count} degraded, ${monitoring.unhealthy_count} unhealthy observations`,
  );
  renderServices(monitoring.services);

  setText("sev1-count", incidents.severity_counts["SEV-1"] || 0);
  setText("sev2-count", incidents.severity_counts["SEV-2"] || 0);
  setText("sev3-count", incidents.severity_counts["SEV-3"] || 0);
  state.incidents = incidents.rows;
  renderIncidentRows();

  setText("macro-f1", ai.macro_f1.toFixed(2));
  byId("f1-fill").style.width = `${ai.macro_f1 * 100}%`;
  setText("answered-accuracy", `${ai.accuracy_on_answered_percent}%`);
  setText("review-count", `${ai.human_review_count} / ${ai.fixture_case_count}`);
  setText("threshold", ai.operating_threshold);
}

byId("severity-filter").addEventListener("change", renderIncidentRows);
byId("incident-search").addEventListener("input", renderIncidentRows);

fetch("./data/dashboard.json", { cache: "no-store" })
  .then((response) => {
    if (!response.ok) throw new Error(`Dashboard data returned ${response.status}`);
    return response.json();
  })
  .then(renderDashboard)
  .catch(() => {
    byId("load-error").hidden = false;
  });
