
document.addEventListener("DOMContentLoaded", function () {
  const container = document.getElementById("monitor");

  if (!container) {
    return;
  }

  const statusUrl = container.dataset.statusUrl;
  const pollMs = Number(container.dataset.pollMs);
  const connection = document.getElementById("monitor-connection");
  const rowsBody = document.getElementById("monitor-rows");
  const updated = document.getElementById("monitor-updated");
  const live = document.getElementById("monitor-live");

  let stopped = false;

  function setText(id, value) {
    const element = document.getElementById(id);

    if (element) {
      element.textContent = value;
    }
  }

  function cell(text) {
    const td = document.createElement("td");
    td.textContent = text;
    return td;
  }

  function render(data) {
    Object.keys(data.counts).forEach(function (status) {
      setText("count-" + status, data.counts[status]);
    });

    setText("count-total", data.total);
    live.textContent = data.is_live ? "Live" : "Not running";
    updated.textContent = data.generated_display;
    updated.setAttribute("datetime", data.generated_at);

    const rows = document.createDocumentFragment();

    data.rows.forEach(function (row) {
      const tr = document.createElement("tr");
      tr.dataset.status = row.status;

      tr.appendChild(
        cell(row.username + (row.enrolled ? "" : " (not enrolled)"))
      );

      tr.appendChild(cell(row.name));
      tr.appendChild(cell(row.status_label));
      tr.appendChild(cell(row.started_display || "-"));
      tr.appendChild(cell(row.submitted_display || "-"));

      rows.appendChild(tr);
    });

    if (!data.rows.length) {
      const tr = document.createElement("tr");
      const td = cell("No students are enrolled in this course.");

      td.colSpan = 5;
      tr.appendChild(td);
      rows.appendChild(tr);
    }

    rowsBody.replaceChildren(rows);
  }

  function stop(message) {
    stopped = true;
    connection.textContent = message;
  }

  function poll() {
    if (stopped) {
      return;
    }

    fetch(statusUrl, {
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json" },
    })
      .then(function (response) {
        if (
          response.redirected ||
          response.status === 403 ||
          response.status === 404
        ) {
          stop("Live updates stopped. Please reload the page or log in again.");
          return null;
        }

        if (!response.ok) {
          throw new Error("HTTP " + response.status);
        }

        return response.json();
      })
      .then(function (data) {
        if (data) {
          render(data);
          connection.textContent = "";
        }
      })
      .catch(function () {
        connection.textContent = "Connection lost, retrying...";
      })
      .finally(function () {
        if (!stopped) {
          setTimeout(poll, pollMs);
        }
      });
  }

  setTimeout(poll, pollMs);
});
