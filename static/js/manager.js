(() => {
  const root = document.querySelector("[data-manager-employees]");
  if (!root) {
    return;
  }

  const section = document.querySelector("[data-employee-section]") || root;
  const tableBody = section.querySelector("[data-employee-rows]");
  const rows = tableBody
    ? Array.from(tableBody.querySelectorAll("tr[data-employee-row]"))
    : [];
  const emptyRow = tableBody ? tableBody.querySelector("[data-empty-row]") : null;
  const searchInput = section.querySelector("[data-employee-search]");
  const positionFilter = section.querySelector("[data-employee-position-filter]");
  const statusFilter = section.querySelector("[data-employee-status-filter]");
  const countLabel = section.querySelector("[data-employee-count]");
  const statusTabs = Array.from(section.querySelectorAll("[data-status-tab]"));
  const resetButton = section.querySelector("[data-employee-reset]");

  let statusTabValue = "all";

  const normalize = (value) =>
    String(value || "")
      .toLowerCase()
      .replace(/\s+/g, " ")
      .trim();

  const updateCountLabel = (visibleCount) => {
    if (!countLabel) {
      return;
    }
    countLabel.textContent = `Показано: ${visibleCount} из ${rows.length}`;
  };

  const getFilterValue = (input) => normalize(input ? input.value : "");

  const applyFilters = () => {
    const searchValue = getFilterValue(searchInput);
    const positionValue = getFilterValue(positionFilter);
    const statusValue = getFilterValue(statusFilter);
    let visibleCount = 0;

    rows.forEach((row) => {
      const name = normalize(row.dataset.name || "");
      const position = normalize(row.dataset.position || "");
      const phone = normalize(row.dataset.phone || "");
      const email = normalize(row.dataset.email || "");
      const status = normalize(row.dataset.status || "");

      const matchesSearch =
        !searchValue ||
        name.includes(searchValue) ||
        position.includes(searchValue) ||
        phone.includes(searchValue) ||
        email.includes(searchValue);
      const matchesPosition = !positionValue || position === positionValue;
      const matchesStatus = !statusValue || status === statusValue;
      const matchesTab =
        statusTabValue === "all" ||
        (statusTabValue === "active" && status !== "inactive") ||
        (statusTabValue === "inactive" && status === "inactive");

      const shouldShow = matchesSearch && matchesPosition && matchesStatus && matchesTab;
      row.hidden = !shouldShow;
      row.style.display = shouldShow ? "" : "none";
      if (shouldShow) {
        visibleCount += 1;
      }
    });

    if (emptyRow) {
      emptyRow.hidden = visibleCount > 0;
    }
    updateCountLabel(visibleCount);
  };

  if (searchInput) {
    searchInput.addEventListener("input", () => {
      applyFilters();
    });
  }

  if (positionFilter) {
    positionFilter.addEventListener("change", () => {
      applyFilters();
    });
  }

  if (statusFilter) {
    statusFilter.addEventListener("change", () => {
      applyFilters();
    });
  }

  statusTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      statusTabs.forEach((btn) => btn.classList.remove("active"));
      tab.classList.add("active");
      statusTabValue = tab.dataset.statusTab || "all";
      applyFilters();
    });
  });

  if (resetButton) {
    resetButton.addEventListener("click", () => {
      if (searchInput) {
        searchInput.value = "";
        searchInput.dispatchEvent(new Event("input", { bubbles: true }));
      }
      if (positionFilter) {
        positionFilter.value = "";
        positionFilter.dispatchEvent(new Event("change", { bubbles: true }));
      }
      if (statusFilter) {
        statusFilter.value = "";
        statusFilter.dispatchEvent(new Event("change", { bubbles: true }));
      }
      if (statusTabs.length) {
        statusTabs.forEach((btn) => btn.classList.remove("active"));
        statusTabs[0].classList.add("active");
        statusTabValue = statusTabs[0].dataset.statusTab || "all";
      } else {
        statusTabValue = "all";
      }
      applyFilters();
    });
  }

  applyFilters();
})();

(() => {
  const root = document.querySelector("[data-manager-employee-detail]");
  if (!root) {
    return;
  }

  const absenceUrl = root.dataset.absenceUrl || "";
  const isActive = root.dataset.employeeActive !== "false";
  const statusPill = root.querySelector("[data-employee-status-pill]");
  const statusLabel = root.querySelector("[data-employee-status-label]");

  const typeTabs = Array.from(root.querySelectorAll("[data-absence-type]"));
  const absenceRange = root.querySelector("[data-absence-range]");
  const vacationBalance = root.querySelector("[data-vacation-balance]");
  const vacationBalanceValue = root.querySelector("[data-vacation-balance-value]");
  const absenceHint = root.querySelector("[data-absence-hint]");
  const calendarTitle = root.querySelector("[data-calendar-title]");
  const calendarGrid = root.querySelector("[data-calendar-grid]");
  const calendarPrev = root.querySelector("[data-calendar-prev]");
  const calendarNext = root.querySelector("[data-calendar-next]");
  const absenceMessage = root.querySelector("[data-absence-message]");
  const absenceSave = root.querySelector("[data-absence-save]");
  const absenceReset = root.querySelector("[data-absence-reset]");
  const absenceList = root.querySelector("[data-absence-list]");

  const statusMap = {
    active: { label: "Активен", className: "success" },
    vacation: { label: "В отпуске", className: "warning" },
    sick: { label: "Больничный", className: "danger" },
    inactive: { label: "Неактивен", className: "muted" },
  };

  let selectedAbsences = [];
  const initialTab = typeTabs.find((tab) => tab.classList.contains("active"));
  let currentAbsenceType = initialTab?.dataset.absenceType || "vacation";
  let rangeStart = null;
  let rangeEnd = null;
  let calendarMonth = new Date();

  const pad = (value) => String(value).padStart(2, "0");

  const toDateOnly = (value) =>
    new Date(value.getFullYear(), value.getMonth(), value.getDate());

  const toISODate = (value) =>
    `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`;

  const parseISODate = (value) => {
    if (!value) {
      return null;
    }
    const [year, month, day] = String(value).split("-").map(Number);
    if (!year || !month || !day) {
      return null;
    }
    return new Date(year, month - 1, day);
  };

  const formatDate = (value) => {
    if (!value) {
      return "—";
    }
    return `${pad(value.getDate())}.${pad(value.getMonth() + 1)}.${value.getFullYear()}`;
  };

  const formatRange = (start, end) => {
    if (!start) {
      return "—";
    }
    if (!end) {
      return `${formatDate(start)} —`;
    }
    return `${formatDate(start)} — ${formatDate(end)}`;
  };

  const isSameDay = (left, right) =>
    left &&
    right &&
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth() &&
    left.getDate() === right.getDate();

  const isBetween = (value, start, end) => {
    if (!value || !start || !end) {
      return false;
    }
    return value >= start && value <= end;
  };

  const getCookie = (name) => {
    const cookieValue = document.cookie
      .split(";")
      .map((cookie) => cookie.trim())
      .find((cookie) => cookie.startsWith(`${name}=`));
    return cookieValue ? decodeURIComponent(cookieValue.split("=")[1]) : "";
  };

  const showMessage = (target, text, type) => {
    if (!target) {
      return;
    }
    target.textContent = text || "";
    target.classList.remove("is-error", "is-success", "is-warning");
    if (!text) {
      target.hidden = true;
      return;
    }
    target.hidden = false;
    if (type === "error") {
      target.classList.add("is-error");
    } else if (type === "warning") {
      target.classList.add("is-warning");
    } else {
      target.classList.add("is-success");
    }
  };

  const extractErrorMessage = (data) => {
    if (!data) {
      return "";
    }
    if (typeof data === "string") {
      return data;
    }
    if (Array.isArray(data)) {
      return data.join(" ");
    }
    if (data.detail) {
      return data.detail;
    }
    if (data.non_field_errors) {
      return Array.isArray(data.non_field_errors)
        ? data.non_field_errors.join(" ")
        : data.non_field_errors;
    }
    const firstKey = Object.keys(data)[0];
    if (!firstKey) {
      return "";
    }
    const value = data[firstKey];
    return Array.isArray(value) ? value.join(" ") : String(value);
  };

  const updateStatusPill = (status) => {
    const statusInfo = statusMap[status] || statusMap.active;
    if (statusPill) {
      statusPill.textContent = statusInfo.label;
      statusPill.className = "status-pill";
      if (statusInfo.className) {
        statusPill.classList.add(statusInfo.className);
      }
    }
    if (statusLabel) {
      statusLabel.textContent = statusInfo.label;
    }
  };

  const getStatusFromAbsences = (absences) => {
    if (!isActive) {
      return "inactive";
    }
    const today = toDateOnly(new Date());
    const current = absences.find((absence) => {
      const start = parseISODate(absence.start_date);
      const end = parseISODate(absence.end_date);
      return start && end && today >= start && today <= end;
    });
    if (current && current.absence_type) {
      return current.absence_type;
    }
    return "active";
  };

  const renderAbsenceList = (absences) => {
    if (!absenceList) {
      return;
    }
    if (!absences.length) {
      absenceList.innerHTML = '<div class="subtle">Нет данных.</div>';
      return;
    }
    const statusLabels = {
      current: "Текущий",
      upcoming: "Запланирован",
      past: "Завершен",
    };
    absenceList.innerHTML = "";
    absences.forEach((absence) => {
      const wrapper = document.createElement("div");
      wrapper.className = "absence-item";
      const title = document.createElement("div");
      title.className = "absence-item-title";
      title.textContent = absence.type_label || "Отсутствие";
      const meta = document.createElement("div");
      meta.className = "absence-item-meta";
      const start = parseISODate(absence.start_date);
      const end = parseISODate(absence.end_date);
      const days = absence.days || (start && end ? (end - start) / 86400000 + 1 : "");
      const daysLabel = days ? `${days} дн.` : "";
      const statusLabel = statusLabels[absence.status] || "";
      meta.textContent = `${formatRange(start, end)} ${daysLabel ? `· ${daysLabel}` : ""} ${statusLabel ? `· ${statusLabel}` : ""}`.trim();
      const pill = document.createElement("span");
      pill.className = "status-pill";
      if (absence.absence_type === "vacation") {
        pill.classList.add("warning");
      } else if (absence.absence_type === "sick") {
        pill.classList.add("danger");
      } else {
        pill.classList.add("muted");
      }
      pill.textContent = absence.type_label || "Отсутствие";
      const content = document.createElement("div");
      content.append(title, meta);
      wrapper.append(content, pill);
      absenceList.append(wrapper);
    });
  };

  const getVacationUsage = (year, absences) => {
    const vacations = absences.filter(
      (absence) => absence.absence_type === "vacation" && parseISODate(absence.start_date)?.getFullYear() === year
    );
    const daysUsed = vacations.reduce((sum, absence) => sum + (absence.days || 0), 0);
    return {
      daysUsed,
      periodsUsed: vacations.length,
      remainingDays: Math.max(0, 28 - daysUsed),
      remainingPeriods: Math.max(0, 2 - vacations.length),
    };
  };

  const getSelectionDays = () => {
    if (!rangeStart || !rangeEnd) {
      return 0;
    }
    return Math.round((rangeEnd - rangeStart) / 86400000) + 1;
  };

  const updateAbsenceMeta = () => {
    if (!absenceRange) {
      return;
    }
    const days = getSelectionDays();
    const rangeText = formatRange(rangeStart, rangeEnd);
    absenceRange.textContent = days ? `${rangeText} · ${days} дн.` : rangeText;
  };

  const updateAbsenceHint = () => {
    if (!absenceHint) {
      return;
    }
    absenceHint.textContent =
      currentAbsenceType === "vacation"
        ? "От 14 до 28 дней, максимум 2 периода"
        : "Можно отметить любой период";
  };

  const updateVacationBalance = () => {
    if (!vacationBalance || !vacationBalanceValue) {
      return;
    }
    if (currentAbsenceType !== "vacation") {
      vacationBalance.hidden = true;
      return;
    }
    const year = rangeStart ? rangeStart.getFullYear() : new Date().getFullYear();
    const usage = getVacationUsage(year, selectedAbsences);
    vacationBalance.hidden = false;
    vacationBalanceValue.textContent = `${usage.daysUsed} из 28 дней, периодов: ${usage.periodsUsed}/2`;
  };

  const validateSelection = () => {
    if (!rangeStart || !rangeEnd) {
      return { valid: false, message: "Выберите начало и конец периода." };
    }
    const overlap = selectedAbsences.some((absence) => {
      const start = parseISODate(absence.start_date);
      const end = parseISODate(absence.end_date);
      return start && end && rangeStart <= end && rangeEnd >= start;
    });
    if (overlap) {
      return { valid: false, message: "Период пересекается с уже отмеченным отсутствием." };
    }
    if (currentAbsenceType !== "vacation") {
      return { valid: true };
    }
    if (rangeStart.getFullYear() !== rangeEnd.getFullYear()) {
      return { valid: false, message: "Отпуск должен быть в пределах одного календарного года." };
    }
    const usage = getVacationUsage(rangeStart.getFullYear(), selectedAbsences);
    const daysSelected = getSelectionDays();
    if (daysSelected < 14) {
      return { valid: false, message: "Отпуск должен быть не менее 14 дней." };
    }
    if (usage.remainingPeriods <= 0) {
      return { valid: false, message: "Лимит отпусков на год уже исчерпан." };
    }
    if (daysSelected > 28) {
      return { valid: false, message: "Отпуск не может превышать 28 дней." };
    }
    if (daysSelected > usage.remainingDays) {
      return { valid: false, message: "Недостаточно доступных дней отпуска." };
    }
    return { valid: true };
  };

  const updateAbsenceState = () => {
    updateAbsenceMeta();
    updateVacationBalance();
    updateAbsenceHint();
    if (!rangeStart || !rangeEnd) {
      if (absenceSave) {
        absenceSave.disabled = true;
      }
      showMessage(absenceMessage, "", "success");
      return;
    }
    const validation = validateSelection();
    if (absenceSave) {
      absenceSave.disabled = !validation.valid;
    }
    if (!validation.valid) {
      showMessage(absenceMessage, validation.message, "warning");
    } else {
      showMessage(absenceMessage, "", "success");
    }
  };

  const renderCalendar = () => {
    if (!calendarGrid) {
      return;
    }
    calendarGrid.innerHTML = "";
    const monthStart = new Date(calendarMonth.getFullYear(), calendarMonth.getMonth(), 1);
    const monthEnd = new Date(calendarMonth.getFullYear(), calendarMonth.getMonth() + 1, 0);
    const monthLabel = monthStart.toLocaleString("ru-RU", { month: "long", year: "numeric" });
    if (calendarTitle) {
      calendarTitle.textContent = monthLabel.charAt(0).toUpperCase() + monthLabel.slice(1);
    }

    const startWeekday = (monthStart.getDay() + 6) % 7;
    const daysInMonth = monthEnd.getDate();
    const today = toDateOnly(new Date());

    const totalCells = Math.ceil((startWeekday + daysInMonth) / 7) * 7;

    for (let index = 0; index < totalCells; index += 1) {
      const dayNumber = index - startWeekday + 1;
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = "absence-day";

      if (dayNumber < 1 || dayNumber > daysInMonth) {
        cell.classList.add("is-empty");
        cell.disabled = true;
        cell.innerHTML = '<div class="absence-day-number">-</div>';
        calendarGrid.append(cell);
        continue;
      }

      const date = new Date(monthStart.getFullYear(), monthStart.getMonth(), dayNumber);
      const iso = toISODate(date);
      cell.dataset.date = iso;

      const absenceForDay = selectedAbsences.find((absence) => {
        const start = parseISODate(absence.start_date);
        const end = parseISODate(absence.end_date);
        return start && end && date >= start && date <= end;
      });

      if (absenceForDay) {
        if (absenceForDay.absence_type === "vacation") {
          cell.classList.add("is-vacation");
        } else if (absenceForDay.absence_type === "sick") {
          cell.classList.add("is-sick");
        }
        cell.classList.add("is-blocked");
        cell.disabled = true;
      }

      if (isSameDay(date, today)) {
        cell.classList.add("is-today");
      }

      if (rangeStart && isSameDay(date, rangeStart)) {
        cell.classList.add("is-selected");
      }
      if (rangeEnd && isSameDay(date, rangeEnd)) {
        cell.classList.add("is-selected");
      }
      if (rangeStart && rangeEnd && isBetween(date, rangeStart, rangeEnd)) {
        cell.classList.add("is-range");
      }

      cell.innerHTML = `<div class="absence-day-number">${dayNumber}</div>`;
      calendarGrid.append(cell);
    }
  };

  const loadAbsences = async () => {
    if (!absenceUrl) {
      return [];
    }
    try {
      const response = await fetch(absenceUrl, { credentials: "same-origin" });
      if (!response.ok) {
        throw new Error("load failed");
      }
      const data = await response.json();
      return Array.isArray(data) ? data : [];
    } catch (error) {
      return [];
    }
  };

  const resetSelection = () => {
    rangeStart = null;
    rangeEnd = null;
    renderCalendar();
    updateAbsenceState();
  };

  typeTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      typeTabs.forEach((btn) => btn.classList.remove("active"));
      tab.classList.add("active");
      currentAbsenceType = tab.dataset.absenceType || "vacation";
      resetSelection();
      updateAbsenceHint();
      updateVacationBalance();
    });
  });

  if (calendarPrev) {
    calendarPrev.addEventListener("click", () => {
      calendarMonth = new Date(calendarMonth.getFullYear(), calendarMonth.getMonth() - 1, 1);
      renderCalendar();
    });
  }

  if (calendarNext) {
    calendarNext.addEventListener("click", () => {
      calendarMonth = new Date(calendarMonth.getFullYear(), calendarMonth.getMonth() + 1, 1);
      renderCalendar();
    });
  }

  if (calendarGrid) {
    calendarGrid.addEventListener("click", (event) => {
      const button = event.target.closest(".absence-day");
      if (!button || button.classList.contains("is-empty") || button.disabled) {
        return;
      }
      const dateValue = parseISODate(button.dataset.date);
      if (!dateValue) {
        return;
      }
      if (!rangeStart || (rangeStart && rangeEnd)) {
        rangeStart = dateValue;
        rangeEnd = null;
      } else if (dateValue < rangeStart) {
        rangeEnd = rangeStart;
        rangeStart = dateValue;
      } else {
        rangeEnd = dateValue;
      }
      renderCalendar();
      updateAbsenceState();
    });
  }

  if (absenceReset) {
    absenceReset.addEventListener("click", () => {
      resetSelection();
    });
  }

  if (absenceSave) {
    absenceSave.addEventListener("click", async () => {
      if (!rangeStart || !rangeEnd) {
        return;
      }
      const validation = validateSelection();
      if (!validation.valid) {
        showMessage(absenceMessage, validation.message, "warning");
        return;
      }
      if (!absenceUrl) {
        showMessage(absenceMessage, "Не удалось сохранить отсутствие.", "error");
        return;
      }
      try {
        const response = await fetch(absenceUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCookie("csrftoken"),
          },
          body: JSON.stringify({
            absence_type: currentAbsenceType,
            start_date: toISODate(rangeStart),
            end_date: toISODate(rangeEnd),
          }),
        });
        if (!response.ok) {
          const data = await response.json();
          const message = extractErrorMessage(data) || "Не удалось сохранить отсутствие.";
          showMessage(absenceMessage, message, "error");
          return;
        }
        const saved = await response.json();
        selectedAbsences = [saved, ...selectedAbsences].sort((a, b) =>
          a.start_date < b.start_date ? 1 : -1
        );
        renderAbsenceList(selectedAbsences);
        updateStatusPill(getStatusFromAbsences(selectedAbsences));
        resetSelection();
        showMessage(absenceMessage, "Отсутствие сохранено.", "success");
      } catch (error) {
        showMessage(absenceMessage, "Не удалось сохранить отсутствие.", "error");
      }
    });
  }

  const init = async () => {
    selectedAbsences = await loadAbsences();
    renderAbsenceList(selectedAbsences);
    updateStatusPill(getStatusFromAbsences(selectedAbsences));
    updateAbsenceHint();
    updateAbsenceState();
    renderCalendar();
  };

  init();
})();

const initManagerCalendar = (calendarRoot) => {
  const root = calendarRoot || document.querySelector("[data-manager-calendar]");
  if (!root || root.dataset.managerCalendarReady === "true") {
    return;
  }
  root.dataset.managerCalendarReady = "true";

  const approveUrl = root.dataset.approveUrl || "";
  const requestUpdateUrl = root.dataset.requestUpdateUrl || "";
  const approveButton = root.querySelector("[data-schedule-approve]");
  const generateButton = root.querySelector("[data-schedule-generate]");
  const messageEl = root.querySelector("[data-schedule-message]");
  const statusPill = root.querySelector("[data-schedule-status]");
  const toggleCandidates = root.querySelector("[data-toggle-candidates]");
  const weekStart = root.dataset.weekStart;
  const weekEnd = root.dataset.weekEnd;
  const scheduleApproved = root.dataset.scheduleApproved === "true";
  const requestButtons = Array.from(root.querySelectorAll("[data-request-action]"));
  const manualModal = root.querySelector("[data-modal='manual-shift']");
  const manualEmployee = manualModal ? manualModal.querySelector("[data-manual-employee]") : null;
  const manualDateLabel = manualModal ? manualModal.querySelector("[data-manual-date-label]") : null;
  const manualStart = manualModal ? manualModal.querySelector("[data-manual-start]") : null;
  const manualEnd = manualModal ? manualModal.querySelector("[data-manual-end]") : null;
  const manualSave = manualModal ? manualModal.querySelector("[data-manual-save]") : null;
  const manualError = manualModal ? manualModal.querySelector("[data-manual-error]") : null;
  const shiftCells = Array.from(root.querySelectorAll("[data-shift-cell]"));
  const cellWraps = Array.from(root.querySelectorAll("[data-cell-wrap]"));
  const weekNavLinks = Array.from(root.querySelectorAll("[data-week-nav]"));

  let dragState = null;
  let manualContext = null;
  let isLoading = false;

  const getCookie = (name) => {
    const cookieValue = document.cookie
      .split(";")
      .map((cookie) => cookie.trim())
      .find((cookie) => cookie.startsWith(`${name}=`));
    return cookieValue ? decodeURIComponent(cookieValue.split("=")[1]) : "";
  };

  const showMessage = (text, type) => {
    if (!messageEl) {
      return;
    }
    messageEl.textContent = text || "";
    messageEl.classList.remove("is-error", "is-success", "is-warning");
    if (!text) {
      messageEl.hidden = true;
      return;
    }
    messageEl.hidden = false;
    if (type === "error") {
      messageEl.classList.add("is-error");
    } else if (type === "warning") {
      messageEl.classList.add("is-warning");
    } else {
      messageEl.classList.add("is-success");
    }
  };

  const showManualError = (text) => {
    if (!manualError) {
      return;
    }
    manualError.textContent = text || "";
    if (!text) {
      manualError.hidden = true;
      manualError.classList.remove("is-error");
      return;
    }
    manualError.hidden = false;
    manualError.classList.add("is-error");
  };

  const formatManualDate = (value) => {
    const [year, month, day] = String(value || "").split("-");
    if (!year || !month || !day) {
      return "—";
    }
    return `${day}.${month}.${year}`;
  };

  const setManualSelectValue = (select, value) => {
    if (!select) {
      return;
    }
    select.value = value || "";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  };

  const openModal = (modal) => {
    if (!modal) {
      return;
    }
    modal.removeAttribute("hidden");
    modal.removeAttribute("inert");
    modal.classList.add("is-open");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
  };

  const closeModal = (modal) => {
    if (!modal) {
      return;
    }
    modal.classList.remove("is-open");
    modal.setAttribute("aria-hidden", "true");
    modal.setAttribute("inert", "");
    modal.setAttribute("hidden", "");
    document.body.classList.remove("modal-open");
  };

  const syncCustomSelects = (scope) => {
    if (typeof window.initCustomSelects === "function") {
      window.initCustomSelects(scope || document);
    }
  };

  const loadWeek = async (url, options = {}) => {
    if (!url || isLoading) {
      return;
    }
    isLoading = true;
    if (root && root.isConnected) {
      root.classList.add("is-loading");
    }
    const shouldPush = options.push !== false;
    try {
      const response = await fetch(url, {
        headers: {
          "X-Requested-With": "XMLHttpRequest",
        },
      });
      if (!response.ok) {
        throw new Error("Bad response");
      }
      const html = await response.text();
      const doc = new DOMParser().parseFromString(html, "text/html");
      const nextRoot = doc.querySelector("[data-manager-calendar]");
      if (!nextRoot) {
        throw new Error("Calendar not found");
      }
      root.replaceWith(nextRoot);
      if (shouldPush) {
        window.history.pushState({}, "", url);
      }
      syncCustomSelects(nextRoot);
      initManagerCalendar(nextRoot);
    } catch (error) {
      if (shouldPush) {
        window.location.href = url;
      } else {
        window.location.reload();
      }
    } finally {
      isLoading = false;
      if (root && root.isConnected) {
        root.classList.remove("is-loading");
      }
    }
  };

  window.__managerCalendarLoadWeek = loadWeek;
  if (!window.__managerCalendarPopstateBound) {
    window.addEventListener("popstate", () => {
      if (typeof window.__managerCalendarLoadWeek === "function") {
        window.__managerCalendarLoadWeek(window.location.href, { push: false });
      }
    });
    window.__managerCalendarPopstateBound = true;
  }

  if (weekNavLinks.length) {
    weekNavLinks.forEach((link) => {
      link.addEventListener("click", (event) => {
        event.preventDefault();
        loadWeek(link.href);
      });
    });
  }

  const cellsBySlot = new Map();
  const registerShiftCell = (cell) => {
    const slotKey = cell.dataset.slotKey;
    if (!slotKey) {
      return;
    }
    if (!cellsBySlot.has(slotKey)) {
      cellsBySlot.set(slotKey, []);
    }
    const list = cellsBySlot.get(slotKey);
    if (!list.includes(cell)) {
      list.push(cell);
    }
  };

  const unregisterShiftCell = (cell) => {
    const slotKey = cell.dataset.slotKey;
    if (!slotKey || !cellsBySlot.has(slotKey)) {
      return;
    }
    const list = cellsBySlot.get(slotKey).filter((item) => item !== cell);
    if (list.length) {
      cellsBySlot.set(slotKey, list);
    } else {
      cellsBySlot.delete(slotKey);
    }
  };

  shiftCells.forEach((cell) => registerShiftCell(cell));

  const setAssigned = (slotKey, userId) => {
    const cells = cellsBySlot.get(slotKey) || [];
    cells.forEach((cell) => {
      const isAssigned = userId ? cell.dataset.userId === String(userId) : false;
      cell.classList.toggle("is-assigned", isAssigned);
      cell.dataset.assigned = isAssigned ? "true" : "false";
      const tag = cell.querySelector(".shift-tag");
      if (tag) {
        tag.textContent = isAssigned ? "Назначен" : "Не назначен";
        tag.classList.toggle("is-muted", !isAssigned);
      }
    });
  };

  const handleDragStart = (event) => {
    if (scheduleApproved) {
      return;
    }
    const cell = event.currentTarget;
    const slotKey = cell.dataset.slotKey;
    if (!slotKey) {
      return;
    }
    dragState = { slotKey };
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", slotKey);
  };

  const handleDragEnd = () => {
    shiftCells.forEach((cell) => cell.classList.remove("is-drop-target"));
    dragState = null;
  };

  const handleDrop = (event, target) => {
    event.preventDefault();
    const slotKey = dragState?.slotKey || event.dataTransfer.getData("text/plain");
    const targetSlotKey = target.dataset.slotKey;
    target.classList.remove("is-drop-target");
    if (!slotKey || slotKey !== targetSlotKey) {
      showMessage("Можно менять назначение только внутри одинакового времени.", "warning");
      return;
    }
    setAssigned(targetSlotKey, target.dataset.userId);
  };

  const attachShiftCellHandlers = (cell) => {
    if (!cell) {
      return;
    }
    cell.addEventListener("dragstart", handleDragStart);
    cell.addEventListener("dragend", handleDragEnd);
    cell.addEventListener("click", () => {
      if (scheduleApproved) {
        return;
      }
      const slotKey = cell.dataset.slotKey;
      if (!slotKey) {
        return;
      }
      const isManual = cell.dataset.manual === "true";
      const isAssigned = cell.classList.contains("is-assigned");
      if (isManual && isAssigned) {
        const wrap = cell.closest("[data-cell-wrap]");
        unregisterShiftCell(cell);
        if (wrap && wrap.dataset.emptyHtml) {
          wrap.innerHTML = wrap.dataset.emptyHtml;
          attachManualControls(wrap);
        }
        return;
      }
      if (isAssigned) {
        setAssigned(slotKey, null);
      } else {
        setAssigned(slotKey, cell.dataset.userId);
      }
    });
    cell.addEventListener("dragover", (event) => {
      if (scheduleApproved) {
        return;
      }
      const slotKey = dragState?.slotKey;
      if (slotKey && slotKey === cell.dataset.slotKey) {
        event.preventDefault();
        cell.classList.add("is-drop-target");
      }
    });
    cell.addEventListener("dragleave", () => {
      cell.classList.remove("is-drop-target");
    });
    cell.addEventListener("drop", (event) => {
      if (scheduleApproved) {
        return;
      }
      handleDrop(event, cell);
    });
  };

  shiftCells.forEach((cell) => attachShiftCellHandlers(cell));

  const attachManualControls = (wrap) => {
    if (!wrap) {
      return;
    }
    const addButton = wrap.querySelector("[data-manual-add]");
    if (!addButton) {
      return;
    }
    addButton.addEventListener("click", () => {
      if (scheduleApproved) {
        return;
      }
      if (!manualModal || !manualStart || !manualEnd) {
        return;
      }
      const rawDate = wrap.dataset.date || "";
      manualContext = {
        wrap,
        userId: wrap.dataset.userId,
        employeeName: wrap.dataset.employeeName || "—",
        date: rawDate,
      };
      if (manualEmployee) {
        manualEmployee.textContent = `Сотрудник: ${manualContext.employeeName}`;
      }
      if (manualDateLabel) {
        manualDateLabel.textContent = formatManualDate(rawDate);
      }
      setManualSelectValue(manualStart, "");
      setManualSelectValue(manualEnd, "");
      showManualError("");
      openModal(manualModal);
    });
  };

  cellWraps.forEach((wrap) => {
    if (wrap.querySelector("[data-manual-add]")) {
      wrap.dataset.emptyHtml = wrap.innerHTML;
      attachManualControls(wrap);
    }
  });

  if (manualModal) {
    manualModal.querySelectorAll("[data-action='close-modal']").forEach((btn) => {
      btn.addEventListener("click", () => {
        closeModal(manualModal);
      });
    });
  }

  if (manualSave && manualModal) {
    manualSave.addEventListener("click", () => {
      if (scheduleApproved || !manualContext || !manualStart || !manualEnd) {
        return;
      }
      const date = manualContext.date || "";
      const start = manualStart.value;
      const end = manualEnd.value;
      if (!date) {
        showManualError("Не удалось определить дату слота.");
        return;
      }
      if (!start || !end) {
        showManualError("Заполните время слота.");
        return;
      }
      if (start >= end) {
        showManualError("Время окончания должно быть позже начала.");
        return;
      }
      const timeKey = `${start.replace(":", "")}-${end.replace(":", "")}`;
      const slotKey = `${date}-${timeKey}`;
      const wrap = manualContext.wrap;
      const userId = manualContext.userId;

      const cell = document.createElement("div");
      cell.className = "shift-block shift-cell is-assigned";
      cell.draggable = true;
      cell.dataset.shiftCell = "";
      cell.dataset.slotKey = slotKey;
      cell.dataset.userId = userId;
      cell.dataset.date = date;
      cell.dataset.start = start;
      cell.dataset.end = end;
      cell.dataset.priority = "mid";
      cell.dataset.manual = "true";
      cell.title = "Смена добавлена вручную";
      cell.innerHTML = `
        <div class="shift-meta">
          <span class="priority-flag is-mid">Ок</span>
          <span class="shift-tag">Назначен</span>
        </div>
        <div class="shift-time">${start}-${end}</div>
      `;

      wrap.innerHTML = "";
      wrap.appendChild(cell);
      registerShiftCell(cell);
      attachShiftCellHandlers(cell);
      closeModal(manualModal);
      showMessage("Смена добавлена вручную без пожелания сотрудника.", "warning");
    });
  }

  if (toggleCandidates) {
    const syncToggleLabel = (hidden) => {
      toggleCandidates.classList.toggle("is-active", !hidden);
      toggleCandidates.textContent = hidden ? "Показать пожелания" : "Скрыть пожелания";
    };
    syncToggleLabel(root.classList.contains("hide-candidates"));
    toggleCandidates.addEventListener("click", () => {
      const isHidden = root.classList.toggle("hide-candidates");
      syncToggleLabel(isHidden);
    });
  }

  if (generateButton) {
    generateButton.addEventListener("click", () => {
      window.location.reload();
    });
  }

  if (!shiftCells.length && approveButton) {
    approveButton.disabled = true;
  }

  const buildDateRange = () => {
    if (!weekStart || !weekEnd) {
      return [];
    }
    const start = new Date(`${weekStart}T00:00:00`);
    const end = new Date(`${weekEnd}T00:00:00`);
    const dates = [];
    for (let current = new Date(start); current <= end; current.setDate(current.getDate() + 1)) {
      const year = current.getFullYear();
      const month = String(current.getMonth() + 1).padStart(2, "0");
      const day = String(current.getDate()).padStart(2, "0");
      dates.push(`${year}-${month}-${day}`);
    }
    return dates;
  };

  if (approveButton && approveUrl) {
    approveButton.addEventListener("click", async () => {
      showMessage("", null);
      approveButton.disabled = true;
      const assignments = [];
      shiftCells.forEach((cell) => {
        if (!cell.classList.contains("is-assigned")) {
          return;
        }
        assignments.push({
          user_id: Number(cell.dataset.userId),
          date: cell.dataset.date,
          start_time: cell.dataset.start,
          end_time: cell.dataset.end,
        });
      });

      try {
        const response = await fetch(approveUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCookie("csrftoken"),
          },
          credentials: "same-origin",
          body: JSON.stringify({
            assignments,
            dates: buildDateRange(),
          }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          showMessage(data.detail || "Не удалось утвердить график.", "error");
          return;
        }
        if (statusPill) {
          statusPill.classList.remove("warning");
          statusPill.classList.add("success");
          statusPill.textContent = "График утвержден";
        }
        showMessage("График утвержден и отправлен сотрудникам.", "success");
        window.setTimeout(() => {
          window.location.reload();
        }, 600);
      } catch (error) {
        showMessage("Ошибка сети. Попробуйте позже.", "error");
      } finally {
        approveButton.disabled = false;
      }
    });
  }

  if (requestButtons.length && requestUpdateUrl) {
    requestButtons.forEach((button) => {
      button.addEventListener("click", async () => {
        const row = button.closest("[data-request-row]");
        if (!row) {
          return;
        }
        const requestId = row.dataset.requestId;
        const decision = button.dataset.decision;
        if (!requestId || !decision) {
          return;
        }
        showMessage("", null);
        button.disabled = true;
        try {
          const response = await fetch(requestUpdateUrl, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": getCookie("csrftoken"),
            },
            credentials: "same-origin",
            body: JSON.stringify({
              request_id: Number(requestId),
              decision,
            }),
          });
          const data = await response.json().catch(() => ({}));
          if (!response.ok) {
            showMessage(data.detail || "Не удалось обновить запрос.", "error");
            return;
          }
          const status = row.querySelector("[data-request-status]");
          if (status) {
            status.classList.remove("warning", "success", "danger");
            status.classList.add(decision === "approved" ? "success" : "danger");
            status.textContent = decision === "approved" ? "Одобрено" : "Отклонено";
          }
          row.querySelectorAll("[data-request-action]").forEach((actionBtn) => {
            actionBtn.disabled = true;
            actionBtn.remove();
          });
          showMessage("Запрос обновлен. График будет пересчитан.", "success");
          window.setTimeout(() => {
            window.location.reload();
          }, 800);
        } catch (error) {
          showMessage("Ошибка сети. Попробуйте позже.", "error");
        } finally {
          button.disabled = false;
        }
      });
    });
  }

  if (scheduleApproved) {
    root.classList.add("is-locked");
    if (generateButton) {
      generateButton.disabled = true;
    }
    if (approveButton) {
      approveButton.disabled = true;
    }
  }
};

(() => {
  initManagerCalendar(document.querySelector("[data-manager-calendar]"));
})();

(() => {
  const initManagerTasks = (tasksRoot) => {
    const root = tasksRoot || document.querySelector("[data-manager-tasks]");
    if (!root || root.dataset.managerTasksReady === "true") {
      return;
    }
    root.dataset.managerTasksReady = "true";

    const filtersForm = root.querySelector("[data-task-filters]");
    const filterSelects = filtersForm ? Array.from(filtersForm.querySelectorAll("select")) : [];
    const weekInput = filtersForm ? filtersForm.querySelector("input[name='week']") : null;
    const resetButton = root.querySelector("[data-filter-reset]");
    const weekNavLinks = Array.from(root.querySelectorAll("[data-week-nav]"));
    const weekPicker = root.querySelector("[data-week-picker]");

    let isLoading = false;

    const loadWeek = async (url, options = {}) => {
      if (!url || isLoading) {
        return;
      }
      isLoading = true;
      root.classList.add("is-loading");
      const shouldPush = options.push !== false;
      try {
        const response = await fetch(url, {
          headers: {
            "X-Requested-With": "XMLHttpRequest",
          },
        });
        if (!response.ok) {
          throw new Error("Bad response");
        }
        const html = await response.text();
        const doc = new DOMParser().parseFromString(html, "text/html");
        const nextRoot = doc.querySelector("[data-manager-tasks]");
        if (!nextRoot) {
          throw new Error("Tasks not found");
        }
        root.replaceWith(nextRoot);
        if (shouldPush) {
          window.history.pushState({}, "", url);
        }
        if (typeof window.initCustomSelects === "function") {
          window.initCustomSelects(nextRoot);
        }
        initManagerTasks(nextRoot);
      } catch (error) {
        window.location.href = url;
      } finally {
        isLoading = false;
        root.classList.remove("is-loading");
      }
    };

    window.__managerTasksLoadWeek = loadWeek;
    if (!window.__managerTasksPopstateBound) {
      window.addEventListener("popstate", () => {
        if (!document.querySelector("[data-manager-tasks]")) {
          return;
        }
        if (typeof window.__managerTasksLoadWeek === "function") {
          window.__managerTasksLoadWeek(window.location.href, { push: false });
        }
      });
      window.__managerTasksPopstateBound = true;
    }

    const buildFilterUrl = () => {
      const url = new URL(window.location.href);
      if (weekInput && weekInput.value !== "") {
        url.searchParams.set("week", weekInput.value);
      }
      filterSelects.forEach((select) => {
        if (!select.name) {
          return;
        }
        const value = select.value || "";
        if (!value || value === "all") {
          url.searchParams.delete(select.name);
        } else {
          url.searchParams.set(select.name, value);
        }
      });
      return url.toString();
    };

    if (filtersForm && filterSelects.length) {
      filterSelects.forEach((select) => {
        select.addEventListener("change", () => {
          loadWeek(buildFilterUrl());
        });
      });
      filtersForm.addEventListener("submit", (event) => {
        event.preventDefault();
        loadWeek(buildFilterUrl());
      });
    }

    if (resetButton && filtersForm) {
      resetButton.addEventListener("click", () => {
        filterSelects.forEach((select) => {
          const defaultOption = select.querySelector("option[value='all']") || select.options[0];
          if (defaultOption) {
            select.value = defaultOption.value;
          }
        });
        loadWeek(buildFilterUrl());
      });
    }

    const getCookie = (name) => {
      if (!document.cookie) {
        return null;
      }
      const csrfCookies = document.cookie
        .split(";")
        .map((cookie) => cookie.trim())
        .filter((cookie) => cookie.startsWith(`${name}=`));
      if (!csrfCookies.length) {
        return null;
      }
      return decodeURIComponent(csrfCookies[0].split("=")[1]);
    };

    const deleteModal = root.querySelector("[data-modal='task-delete']");
    const deleteTitle = deleteModal ? deleteModal.querySelector("[data-task-delete-title]") : null;
    const deleteConfirm = deleteModal
      ? deleteModal.querySelector("[data-task-delete-confirm]")
      : null;
    const extendModal = root.querySelector("[data-modal='task-extend']");
    const extendTitle = extendModal ? extendModal.querySelector("[data-task-extend-title]") : null;
    const extendDate = extendModal ? extendModal.querySelector("[data-task-extend-date]") : null;
    const extendTime = extendModal ? extendModal.querySelector("[data-task-extend-time]") : null;
    const extendConfirm = extendModal
      ? extendModal.querySelector("[data-task-extend-confirm]")
      : null;
    let pendingDeleteUrl = "";
    let pendingExtendUrl = "";

    const syncBodyModalState = () => {
      const openModals = document.querySelectorAll(".modal.is-open");
      document.body.classList.toggle("modal-open", openModals.length > 0);
    };

    const openModal = (modal) => {
      if (!modal) {
        return;
      }
      modal.removeAttribute("hidden");
      modal.removeAttribute("inert");
      modal.classList.add("is-open");
      modal.setAttribute("aria-hidden", "false");
      syncBodyModalState();
      const focusTarget = modal.querySelector("button, [href], input, select, textarea");
      if (focusTarget) {
        focusTarget.focus();
      }
    };

    const resetDeleteState = () => {
      pendingDeleteUrl = "";
      if (deleteConfirm) {
        deleteConfirm.disabled = false;
      }
    };

    const resetExtendState = () => {
      pendingExtendUrl = "";
      if (extendConfirm) {
        extendConfirm.disabled = false;
      }
    };

    const closeModal = (modal) => {
      if (!modal) {
        return;
      }
      modal.classList.remove("is-open");
      modal.setAttribute("aria-hidden", "true");
      modal.setAttribute("inert", "");
      modal.setAttribute("hidden", "");
      syncBodyModalState();
      if (modal === deleteModal) {
        resetDeleteState();
      }
      if (modal === extendModal) {
        resetExtendState();
      }
    };

    const bindModalClose = (modal) => {
      if (!modal) {
        return;
      }
      const closeButtons = modal.querySelectorAll("[data-action='close-modal']");
      closeButtons.forEach((button) => {
        button.addEventListener("click", () => closeModal(modal));
      });
    };

    bindModalClose(deleteModal);
    bindModalClose(extendModal);

    const setSelectValue = (select, value) => {
      if (!select) {
        return;
      }
      const optionExists = Array.from(select.options).some((option) => option.value === value);
      if (value && optionExists) {
        select.value = value;
      } else if (!value) {
        select.value = "";
      } else if (select.options.length) {
        select.value = select.options[0].value;
      }
      select.dispatchEvent(new Event("change", { bubbles: true }));
    };

    const taskRows = Array.from(root.querySelectorAll("[data-task-row]"));
    taskRows.forEach((row) => {
      const toggleButton = row.querySelector("[data-task-toggle]");
      if (toggleButton) {
        toggleButton.addEventListener("click", () => {
          const nextRow = row.nextElementSibling;
          const detailsRow =
            nextRow && nextRow.hasAttribute("data-task-details")
              ? nextRow
              : null;
          if (!detailsRow) {
            return;
          }
          const isOpen = !detailsRow.hidden;
          detailsRow.hidden = isOpen;
          toggleButton.setAttribute("aria-expanded", String(!isOpen));
          row.classList.toggle("is-expanded", !isOpen);
        });
      }

      const deleteButton = row.querySelector("[data-task-delete]");
      if (deleteButton) {
        deleteButton.addEventListener("click", () => {
          const deleteUrl = deleteButton.dataset.deleteUrl;
          if (!deleteUrl) {
            return;
          }
          pendingDeleteUrl = deleteUrl;
          if (deleteTitle) {
            const titleNode = row.querySelector(".task-title");
            deleteTitle.textContent = titleNode ? titleNode.textContent.trim() : "";
          }
          openModal(deleteModal);
        });
      }

      const extendButton = row.querySelector("[data-task-extend]");
      if (extendButton) {
        extendButton.addEventListener("click", () => {
          const extendUrl = extendButton.dataset.extendUrl;
          if (!extendUrl) {
            return;
          }
          pendingExtendUrl = extendUrl;
          if (extendTitle) {
            extendTitle.textContent = row.dataset.taskTitle || "";
          }
          setSelectValue(extendDate, row.dataset.taskDate || "");
          setSelectValue(extendTime, row.dataset.taskDueTime || "");
          openModal(extendModal);
        });
      }
    });

    if (deleteConfirm) {
      deleteConfirm.addEventListener("click", async () => {
        if (!pendingDeleteUrl) {
          return;
        }
        deleteConfirm.disabled = true;
        try {
          const response = await fetch(pendingDeleteUrl, {
            method: "POST",
            headers: {
              "X-Requested-With": "XMLHttpRequest",
              "X-CSRFToken": getCookie("csrftoken"),
            },
            credentials: "same-origin",
          });
          if (!response.ok) {
            throw new Error("Delete failed");
          }
          closeModal(deleteModal);
          loadWeek(buildFilterUrl(), { push: false });
        } catch (error) {
          closeModal(deleteModal);
          window.location.reload();
        } finally {
          deleteConfirm.disabled = false;
          pendingDeleteUrl = "";
        }
      });
    }

    if (extendConfirm) {
      extendConfirm.addEventListener("click", async () => {
        if (!pendingExtendUrl) {
          return;
        }
        extendConfirm.disabled = true;
        try {
          const response = await fetch(pendingExtendUrl, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Requested-With": "XMLHttpRequest",
              "X-CSRFToken": getCookie("csrftoken"),
            },
            credentials: "same-origin",
            body: JSON.stringify({
              date: extendDate ? extendDate.value : "",
              due_time: extendTime ? extendTime.value : "",
            }),
          });
          if (!response.ok) {
            throw new Error("Extend failed");
          }
          closeModal(extendModal);
          loadWeek(buildFilterUrl(), { push: false });
        } catch (error) {
          closeModal(extendModal);
          window.location.reload();
        } finally {
          extendConfirm.disabled = false;
          pendingExtendUrl = "";
        }
      });
    }

    if (weekNavLinks.length) {
      weekNavLinks.forEach((link) => {
        link.addEventListener("click", (event) => {
          event.preventDefault();
          const linkUrl = new URL(link.href, window.location.origin);
          const weekValue = linkUrl.searchParams.get("week") || "current";
          const url = new URL(window.location.href);
          url.searchParams.set("week", weekValue);
          loadWeek(url.toString());
        });
      });
    }

    if (weekPicker) {
      const weekInput = weekPicker.querySelector("[data-week-input]");
      const weekTrigger = weekPicker.querySelector("[data-week-trigger]");
      const weekPanel = weekPicker.querySelector("[data-week-panel]");
      const currentWeekRaw = weekPicker.dataset.currentWeekStart;
      const weekStartRaw = weekPicker.dataset.weekStart;

      const monthNames = [
        "Январь",
        "Февраль",
        "Март",
        "Апрель",
        "Май",
        "Июнь",
        "Июль",
        "Август",
        "Сентябрь",
        "Октябрь",
        "Ноябрь",
        "Декабрь",
      ];
      const weekdayLabels = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

      const parseIso = (value) => {
        if (!value) {
          return null;
        }
        const [year, month, day] = String(value).split("-");
        if (!year || !month || !day) {
          return null;
        }
        return new Date(Number(year), Number(month) - 1, Number(day));
      };

      const getWeekStart = (value) => {
        const dateObj = value instanceof Date ? new Date(value) : parseIso(value);
        if (!dateObj || Number.isNaN(dateObj.getTime())) {
          return null;
        }
        const dayIndex = (dateObj.getDay() + 6) % 7;
        dateObj.setDate(dateObj.getDate() - dayIndex);
        dateObj.setHours(0, 0, 0, 0);
        return dateObj;
      };

      const formatIso = (dateObj) => {
        const year = dateObj.getFullYear();
        const month = String(dateObj.getMonth() + 1).padStart(2, "0");
        const day = String(dateObj.getDate()).padStart(2, "0");
        return `${year}-${month}-${day}`;
      };

      const currentWeekStart = getWeekStart(currentWeekRaw) || getWeekStart(new Date());
      let selectedWeekStart = getWeekStart(weekStartRaw) || currentWeekStart;
      let viewDate = new Date(
        selectedWeekStart.getFullYear(),
        selectedWeekStart.getMonth(),
        1
      );

      const renderCalendar = () => {
        if (!weekPanel) {
          return;
        }
        weekPanel.innerHTML = "";
        const header = document.createElement("div");
        header.className = "date-panel-header";
        const prev = document.createElement("button");
        prev.type = "button";
        prev.textContent = "‹";
        const next = document.createElement("button");
        next.type = "button";
        next.textContent = "›";
        const label = document.createElement("div");
        label.textContent = `${monthNames[viewDate.getMonth()]} ${viewDate.getFullYear()}`;
        header.append(prev, label, next);
        weekPanel.append(header);

        const grid = document.createElement("div");
        grid.className = "date-panel-grid";
        weekdayLabels.forEach((dayLabel) => {
          const cell = document.createElement("div");
          cell.className = "date-panel-weekday";
          cell.textContent = dayLabel;
          grid.append(cell);
        });

        const year = viewDate.getFullYear();
        const month = viewDate.getMonth();
        const firstDay = new Date(year, month, 1);
        const startOffset = (firstDay.getDay() + 6) % 7;
        const daysInMonth = new Date(year, month + 1, 0).getDate();
        const daysInPrev = new Date(year, month, 0).getDate();

        for (let i = 0; i < 42; i += 1) {
          const dayIndex = i - startOffset + 1;
          const cell = document.createElement("div");
          cell.className = "date-panel-day";
          let cellDate;
          if (dayIndex <= 0) {
            const day = daysInPrev + dayIndex;
            cellDate = new Date(year, month - 1, day);
            cell.classList.add("is-muted");
          } else if (dayIndex > daysInMonth) {
            const day = dayIndex - daysInMonth;
            cellDate = new Date(year, month + 1, day);
            cell.classList.add("is-muted");
          } else {
            cellDate = new Date(year, month, dayIndex);
          }
          cell.textContent = String(cellDate.getDate());
          const cellWeekStart = getWeekStart(cellDate);
          if (
            cellWeekStart &&
            selectedWeekStart &&
            cellWeekStart.toDateString() === selectedWeekStart.toDateString()
          ) {
            cell.classList.add("is-week");
          }
          if (
            selectedWeekStart &&
            cellDate.toDateString() === selectedWeekStart.toDateString()
          ) {
            cell.classList.add("is-selected");
          }
          cell.addEventListener("click", () => {
            const newWeekStart = getWeekStart(cellDate);
            if (!newWeekStart || !currentWeekStart) {
              return;
            }
            selectedWeekStart = newWeekStart;
            const offset =
              Math.round((newWeekStart - currentWeekStart) / (7 * 24 * 60 * 60 * 1000)) ||
              0;
            const url = new URL(window.location.href);
            url.searchParams.set("week", String(offset));
            weekPanel.hidden = true;
            loadWeek(url.toString());
          });
          grid.append(cell);
        }

        weekPanel.append(grid);

        prev.addEventListener("click", () => {
          viewDate = new Date(year, month - 1, 1);
          renderCalendar();
        });

        next.addEventListener("click", () => {
          viewDate = new Date(year, month + 1, 1);
          renderCalendar();
        });
      };

      const openPanel = () => {
        if (!weekPanel) {
          return;
        }
        viewDate = new Date(
          selectedWeekStart.getFullYear(),
          selectedWeekStart.getMonth(),
          1
        );
        weekPanel.hidden = false;
        renderCalendar();
      };

      if (weekTrigger) {
        weekTrigger.addEventListener("click", (event) => {
          event.stopPropagation();
          openPanel();
        });
      }

      if (weekInput) {
        weekInput.addEventListener("focus", () => {
          openPanel();
        });
      }

      document.addEventListener("click", (event) => {
        if (weekPanel && !weekPicker.contains(event.target)) {
          weekPanel.hidden = true;
        }
      });
    }
  };

  initManagerTasks(document.querySelector("[data-manager-tasks]"));
})();

(() => {
  const root = document.querySelector("[data-task-create-page]");
  if (!root) {
    return;
  }

  const taskType = root.querySelector("[data-task-type]");
  const taskEmployee = root.querySelector("[data-task-employee]");
  const taskStart = root.querySelector("[data-task-start]");
  const taskEnd = root.querySelector("[data-task-end]");

  const syncTaskType = () => {
    if (!taskType || !taskEmployee) {
      return;
    }
    const isEmployee = taskType.value === "employee";
    taskEmployee.disabled = !isEmployee;
    if (!isEmployee) {
      taskEmployee.value = "";
    }
    taskEmployee.dispatchEvent(new Event("change", { bubbles: true }));
    if (typeof window.initCustomSelects === "function") {
      window.initCustomSelects(root);
    }
  };

  if (taskType) {
    taskType.addEventListener("change", () => {
      syncTaskType();
      if (taskStart && taskEnd && taskType.value !== "slot") {
        return;
      }
    });
  }

  syncTaskType();
})();
