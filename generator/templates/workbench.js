/* 日报工作台（specs/design.md §4.3、ADR-008，v2.0）。

   纯前端：不联网、不上传、不写回 GitHub；手写草稿只存在浏览器 localStorage。
   页面数据来自渲染时内联的 JSON 载荷（id="workbench-data"），因此本脚本不做任何请求。
   v2.0 约定：只有拿到 window 时才运行，页面在无脚本环境下保持 v1.x 的只读形态。 */

(() => {
  "use strict";

  const DATA_ID = "workbench-data";
  const HISTORY_KEY = "daily-report-workbench:history:v1";
  const PENDING_KEY = "daily-report-workbench:pending:v1";
  const HISTORY_LIMIT = 50;

  const dataElement = document.getElementById(DATA_ID);
  let payload = { reports: [] };
  if (dataElement) {
    try {
      payload = JSON.parse(dataElement.textContent) || { reports: [] };
    } catch (error) {
      payload = { reports: [] };
    }
  }
  const reports = Array.isArray(payload.reports) ? payload.reports : [];
  const reportByDate = {};
  reports.forEach((item) => {
    if (item && item.date) reportByDate[item.date] = String(item.markdown || "");
  });

  const toastElement = document.getElementById("toast");
  let toastTimer;

  function showToast(message) {
    if (!toastElement) return;
    toastElement.textContent = message;
    toastElement.dataset.visible = "true";
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => {
      toastElement.dataset.visible = "false";
    }, 2600);
  }

  let storageAvailable = true;
  try {
    const probeKey = HISTORY_KEY + ":probe";
    window.localStorage.setItem(probeKey, "1");
    window.localStorage.removeItem(probeKey);
  } catch (error) {
    storageAvailable = false;
  }

  function readStored(key) {
    if (!storageAvailable) return null;
    try {
      const raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      return null;
    }
  }

  function writeStored(key, value) {
    if (!storageAvailable) return false;
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch (error) {
      return false;
    }
  }

  function dropStored(key) {
    if (!storageAvailable) return;
    try {
      window.localStorage.removeItem(key);
    } catch (error) {
      /* 忽略：隐私模式下删除失败不影响页面 */
    }
  }

  async function writeClipboard(text, fallbackField) {
    if (!text) return false;
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
    if (!fallbackField) return false;
    fallbackField.focus();
    fallbackField.select();
    const copied = document.execCommand("copy");
    if (fallbackField.setSelectionRange) fallbackField.setSelectionRange(0, 0);
    return copied;
  }

  function todayValue() {
    const now = new Date();
    const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 10);
  }

  function linesFrom(element) {
    return element.value
      .split(/\n+/)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function sectionLines(items) {
    return items.length ? items.map((item) => "- " + item) : ["- 未填写"];
  }

  function composeReport(dateValue, todayItems, tomorrowItems, blockerItems) {
    return [
      "# 工作日报 · " + dateValue,
      "",
      "## 今日完成",
      ...sectionLines(todayItems),
      "",
      "## 明日计划",
      ...sectionLines(tomorrowItems),
      "",
      "## 需要协助",
      ...sectionLines(blockerItems),
    ].join("\n");
  }

  function formatStamp(timestamp) {
    const value = Number(timestamp);
    if (!value) return "未知时间";
    try {
      return new Intl.DateTimeFormat("zh-CN", {
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }).format(new Date(value));
    } catch (error) {
      return new Date(value).toLocaleString();
    }
  }

  function summarize(text) {
    const flat = String(text || "")
      .split("\n")
      .map((line) => line.replace(/^#+\s*/, "").trim())
      .filter(Boolean);
    return flat.length ? flat[0].slice(0, 60) : "（空内容）";
  }

  function readHistory() {
    const stored = readStored(HISTORY_KEY);
    if (!Array.isArray(stored)) return [];
    return stored.filter((item) => item && item.date && typeof item.report === "string");
  }

  function saveDraft(dateValue, report) {
    const record = {
      id: dateValue + "-" + Date.now(),
      date: dateValue,
      savedAt: Date.now(),
      report: report,
    };
    const kept = readHistory().filter((item) => item.date !== dateValue);
    kept.unshift(record);
    return writeStored(HISTORY_KEY, kept.slice(0, HISTORY_LIMIT));
  }

  const workbench = document.getElementById("workbench");

  if (workbench) {
    const dateField = document.getElementById("workbench-date");
    const todayField = document.getElementById("workbench-today");
    const tomorrowField = document.getElementById("workbench-tomorrow");
    const blockersField = document.getElementById("workbench-blockers");
    const loadSelect = document.getElementById("workbench-load");
    const outputField = document.getElementById("workbench-output");
    const generateButton = document.getElementById("workbench-generate");
    const sampleButton = document.getElementById("workbench-sample");
    const copyButton = document.getElementById("workbench-copy");
    const statusText = document.getElementById("workbench-status");
    const paperDate = document.getElementById("workbench-paper-date");
    const dateError = document.getElementById("workbench-date-error");
    const todayError = document.getElementById("workbench-today-error");
    const draftList = document.getElementById("draft-list");
    const draftEmpty = document.getElementById("draft-empty");
    const draftStatus = document.getElementById("draft-status");
    const draftNote = document.getElementById("draft-note");
    const clearButton = document.getElementById("draft-clear");

    let generated = false;
    let clearArmed = false;
    let clearTimer;

    function setStatus(message, state) {
      if (!statusText) return;
      statusText.textContent = message;
      statusText.dataset.state = state;
    }

    function setFieldError(field, element, message) {
      if (!field || !element) return;
      field.setAttribute("aria-invalid", message ? "true" : "false");
      element.textContent = message;
      element.classList.toggle("visually-hidden", !message);
    }

    function validate() {
      let firstInvalid = null;
      if (!dateField.value) {
        setFieldError(dateField, dateError, "请选择日报日期。");
        firstInvalid = dateField;
      } else {
        setFieldError(dateField, dateError, "");
      }
      if (!todayField.value.trim()) {
        setFieldError(todayField, todayError, "请至少填写一项今日完成的工作。");
        firstInvalid = firstInvalid || todayField;
      } else {
        setFieldError(todayField, todayError, "");
      }
      if (firstInvalid) firstInvalid.focus();
      return !firstInvalid;
    }

    function fillOutput(dateValue, markdown, message) {
      outputField.value = markdown;
      dateField.value = dateValue || dateField.value;
      if (paperDate) paperDate.textContent = dateField.value || "等待生成";
      copyButton.disabled = !markdown.trim();
      generated = Boolean(markdown.trim());
      // 载入内容后清掉上一次的字段报错，避免旧的"今日完成不能为空"一直挂着
      setFieldError(dateField, dateError, "");
      setFieldError(todayField, todayError, "");
      setStatus(message, markdown.trim() ? "ready" : "empty");
    }

    function createDraftButton(label, extraClass, handler) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "button button-small " + extraClass;
      button.textContent = label;
      button.addEventListener("click", handler);
      return button;
    }

    async function copyText(text, fallbackField, successMessage) {
      try {
        const ok = await writeClipboard(text, fallbackField);
        if (!ok) throw new Error("copy unavailable");
        showToast(successMessage);
      } catch (error) {
        if (fallbackField) {
          fallbackField.focus();
          fallbackField.select();
        }
        showToast("自动复制未成功，内容已选中，请按 Ctrl+C 复制");
      }
    }

    function loadDraft(record) {
      fillOutput(record.date, record.report, "已载入本地草稿 " + record.date + "，可以继续修改");
      showToast("已载入 " + record.date + " 的本地草稿");
      workbench.scrollIntoView({ block: "start", behavior: "smooth" });
    }

    function renderDrafts() {
      if (!draftList) return;
      const records = readHistory().sort((left, right) => (right.savedAt || 0) - (left.savedAt || 0));
      draftList.textContent = "";
      records.forEach((record) => {
        const item = document.createElement("li");
        item.className = "draft-item";

        const info = document.createElement("div");
        info.className = "draft-info";
        const title = document.createElement("p");
        title.className = "draft-date";
        title.textContent = record.date;
        const meta = document.createElement("p");
        meta.className = "draft-meta";
        meta.textContent = "保存于 " + formatStamp(record.savedAt) + " · " + summarize(record.report);
        info.append(title, meta);

        const actions = document.createElement("div");
        actions.className = "draft-actions";
        actions.append(
          createDraftButton("载入", "button-secondary", () => loadDraft(record)),
          createDraftButton("复制", "button-secondary", () =>
            copyText(record.report, outputField, "草稿已复制")
          ),
          createDraftButton("删除", "button-secondary", () => {
            const kept = readHistory().filter((item) => item.id !== record.id);
            writeStored(HISTORY_KEY, kept);
            renderDrafts();
            showToast("已删除 " + record.date + " 的本地草稿");
          })
        );
        item.append(info, actions);
        draftList.append(item);
      });

      const empty = records.length === 0;
      if (draftEmpty) draftEmpty.hidden = !empty;
      draftList.hidden = empty;
      if (draftStatus) {
        draftStatus.textContent = empty
          ? "生成日报后会自动保存在这里"
          : "共 " + records.length + " 篇本地草稿（上限 " + HISTORY_LIMIT + " 篇）";
      }
      if (clearButton) clearButton.disabled = empty;
    }

    function disarmClear() {
      clearArmed = false;
      window.clearTimeout(clearTimer);
      if (clearButton) {
        clearButton.textContent = "清空全部";
        clearButton.classList.add("button-secondary");
      }
    }

    dateField.value = todayValue();
    if (paperDate) paperDate.textContent = "等待生成";

    if (!storageAvailable) {
      if (draftNote) draftNote.textContent = "当前浏览器不允许本地存储，草稿只在本次会话内有效";
      if (clearButton) clearButton.disabled = true;
    }

    [dateField, todayField, tomorrowField, blockersField].forEach((field) => {
      field.addEventListener("input", () => {
        if (!generated) return;
        setStatus("内容已修改，重新生成可同步预览与本地草稿", "empty");
      });
    });

    generateButton.addEventListener("click", () => {
      if (!validate()) return;
      const markdown = composeReport(
        dateField.value,
        linesFrom(todayField),
        linesFrom(tomorrowField),
        linesFrom(blockersField)
      );
      const saved = saveDraft(dateField.value, markdown);
      fillOutput(dateField.value, markdown, saved ? "日报已生成并保存到本地草稿" : "日报已生成，可直接复制");
      renderDrafts();
      outputField.focus();
      showToast(saved ? "已生成并保存到本地草稿" : "已生成（本地草稿不可用）");
    });

    sampleButton.addEventListener("click", () => {
      dateField.value = todayValue();
      todayField.value = "整理本周需求反馈，合并重复问题并补充优先级说明。\n更新任务看板，标记已完成事项并同步剩余工作。";
      tomorrowField.value = "继续跟进高优先级需求，补齐验收记录。";
      blockersField.value = "暂无需要协助的事项。";
      setFieldError(dateField, dateError, "");
      setFieldError(todayField, todayError, "");
      todayField.focus();
      showToast("示例内容已填入，可以按需修改");
    });

    copyButton.addEventListener("click", () => {
      copyText(outputField.value, outputField, "日报已复制，可以粘贴到需要的地方");
    });

    if (loadSelect) {
      loadSelect.addEventListener("change", () => {
        const dateValue = loadSelect.value;
        if (!dateValue) return;
        const markdown = reportByDate[dateValue];
        if (typeof markdown !== "string") {
          showToast("没有找到 " + dateValue + " 的自动日报内容");
          return;
        }
        fillOutput(dateValue, markdown, "已载入 " + dateValue + " 的自动日报，可以继续修改");
        loadSelect.value = "";
        showToast("已载入 " + dateValue + " 的自动日报");
      });
    }

    clearButton.addEventListener("click", () => {
      if (!clearArmed) {
        clearArmed = true;
        clearButton.textContent = "确认清空？";
        showToast("再次点击即可清空全部本地草稿");
        clearTimer = window.setTimeout(disarmClear, 4000);
        return;
      }
      disarmClear();
      dropStored(HISTORY_KEY);
      renderDrafts();
      showToast("本地草稿已清空");
    });

    const pending = readStored(PENDING_KEY);
    if (pending && pending.date && typeof pending.report === "string") {
      fillOutput(pending.date, pending.report, "已载入 " + pending.date + " 的自动日报，可以继续修改");
      dropStored(PENDING_KEY);
    } else if (window.location.hash === "#workbench") {
      setStatus("填写内容后，生成一份日报预览", "empty");
    }

    renderDrafts();
    workbench.hidden = false;
  }

  const detailCopy = document.getElementById("report-copy");
  const detailLoad = document.getElementById("report-load");
  const detailDate = detailCopy ? detailCopy.dataset.date : "";

  function detailMarkdown() {
    return detailDate && typeof reportByDate[detailDate] === "string" ? reportByDate[detailDate] : "";
  }

  if (detailCopy) {
    detailCopy.addEventListener("click", async () => {
      const markdown = detailMarkdown();
      if (!markdown) {
        showToast("这一期没有可复制的 Markdown 内容");
        return;
      }
      try {
        const ok = await writeClipboard(markdown, null);
        if (!ok) throw new Error("copy unavailable");
        showToast("本期日报的 Markdown 已复制");
      } catch (error) {
        showToast("复制失败，请在 https 或 localhost 下重试");
      }
    });
  }

  if (detailLoad) {
    detailLoad.addEventListener("click", () => {
      const markdown = detailMarkdown();
      if (!markdown) {
        showToast("这一期没有可载入的 Markdown 内容");
        return;
      }
      const stored = writeStored(PENDING_KEY, { date: detailDate, report: markdown });
      if (!stored) {
        showToast("当前浏览器不允许本地存储，无法载入到工作台");
        return;
      }
      window.location.href = "index.html#workbench";
    });
  }
})();
