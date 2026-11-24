/* askbase chat widget. Embed with:
   <script src="https://your-askbase-host/widget.js" defer
           data-title="Help" data-color="#1f5f4a"
           data-suggestions="Where is my order?|How do returns work?"></script> */
(() => {
  const script = document.currentScript;
  if (!script || window.__askbase) return;
  window.__askbase = true;

  const cfg = script.dataset;
  const api = (cfg.api || new URL(script.src).origin).replace(/\/$/, "");
  const lang = (cfg.lang || document.documentElement.lang || navigator.language || "en").slice(0, 2);
  const T = {
    en: {
      title: "Help", open: "Ask a question", close: "Close", placeholder: "Ask a question",
      send: "Send", greeting: "Hi! Ask me anything about our products, orders or policies. I answer from our help pages and show you where each answer comes from.",
      sources: "Sources", thinking: "Looking through the help pages",
      unavailable: "The assistant couldn't answer just now. Your question is still here, so you can try again.",
      limited: "That's a lot of questions in a short time. Please wait a minute and try again.",
      offline: "You seem to be offline. Check your connection and try again.",
      retry: "Try again", clear: "New conversation", powered: "Answers come from our help pages and can be wrong. For anything urgent, contact support.",
    },
    tr: {
      title: "Yardım", open: "Soru sor", close: "Kapat", placeholder: "Bir soru sorun",
      send: "Gönder", greeting: "Merhaba! Ürünler, siparişler ya da koşullar hakkında sorun. Yardım sayfalarımızdan cevap veriyor, her bilginin nereden geldiğini gösteriyorum.",
      sources: "Kaynaklar", thinking: "Yardım sayfalarına bakıyorum",
      unavailable: "Asistan şu an cevap veremedi. Sorunuz duruyor, tekrar deneyebilirsiniz.",
      limited: "Kısa sürede çok soru geldi. Bir dakika bekleyip tekrar deneyin.",
      offline: "İnternet bağlantınız yok gibi görünüyor. Bağlantıyı kontrol edip tekrar deneyin.",
      retry: "Tekrar dene", clear: "Yeni sohbet", powered: "Cevaplar yardım sayfalarımızdan gelir ve hatalı olabilir. Acil durumlarda destekle iletişime geçin.",
    },
  };
  const t = { ...(T[lang] || T.en) };
  if (cfg.title) t.title = cfg.title;
  if (cfg.greeting) t.greeting = cfg.greeting;
  const suggestions = (cfg.suggestions || "").split("|").map((s) => s.trim()).filter(Boolean).slice(0, 4);
  const storeKey = `askbase:${api}`;

  const host = document.createElement("div");
  host.setAttribute("data-askbase", "");
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = `<style>
:host { all: initial; font-family: inherit; }
* { box-sizing: border-box; }
.w {
  --accent: ${cfg.color || "oklch(0.42 0.085 165)"};
  --on-accent: ${cfg.onColor || "#fff"};
  --bg: oklch(0.995 0.002 85); --soft: oklch(0.968 0.004 85); --line: oklch(0.905 0.006 85);
  --text: oklch(0.24 0.01 85); --text-2: oklch(0.46 0.01 85); --text-3: oklch(0.54 0.008 85);
  --err: oklch(0.52 0.17 27); --err-bg: oklch(0.965 0.025 27);
  --ease: cubic-bezier(0.23, 1, 0.32, 1);
  font-family: inherit; font-size: 14px; line-height: 1.5; color: var(--text); -webkit-font-smoothing: antialiased;
  position: fixed; z-index: 2147483000; bottom: 20px; ${cfg.position === "left" ? "left" : "right"}: 20px;
}
@media (prefers-color-scheme: dark) {
  .w:not(.light) {
    --bg: oklch(0.215 0.006 85); --soft: oklch(0.255 0.007 85); --line: oklch(0.33 0.007 85);
    --text: oklch(0.945 0.004 85); --text-2: oklch(0.85 0.006 85); --text-3: oklch(0.77 0.006 85);
    --err: oklch(0.72 0.15 25); --err-bg: oklch(0.29 0.05 25);
    ${cfg.color ? (cfg.colorDark ? `--accent: ${cfg.colorDark};` : "") : "--accent: oklch(0.5 0.095 165);"}
  }
}
.launch {
  width: 52px; height: 52px; border-radius: 50%; border: 0; cursor: pointer; display: grid; place-items: center;
  background: var(--accent); color: var(--on-accent);
  box-shadow: 0 1px 2px oklch(0 0 0 / .18), 0 6px 18px -6px oklch(0 0 0 / .35);
  transition: transform 150ms var(--ease), opacity 150ms;
}
.launch:active { transform: scale(.96); }
.launch:focus-visible, button:focus-visible, textarea:focus-visible, a:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.launch svg { width: 24px; height: 24px; }
.panel {
  position: absolute; bottom: 64px; ${cfg.position === "left" ? "left" : "right"}: 0;
  width: 384px; height: min(620px, calc(100vh - 110px)); display: flex; flex-direction: column;
  background: var(--bg); border: 1px solid var(--line); border-radius: 10px; overflow: hidden;
  box-shadow: 0 2px 6px oklch(0 0 0 / .08), 0 18px 48px -12px oklch(0 0 0 / .28);
  transform-origin: bottom ${cfg.position === "left" ? "left" : "right"};
  opacity: 0; transform: translateY(8px) scale(.98); pointer-events: none; visibility: hidden;
  transition: opacity 120ms, transform 120ms, visibility 0s 120ms;
}
.w.open .panel {
  opacity: 1; transform: none; pointer-events: auto; visibility: visible;
  transition: opacity 180ms var(--ease), transform 220ms var(--ease);
}
header { display: flex; align-items: center; gap: 8px; padding: 12px 10px 12px 16px; border-bottom: 1px solid var(--line); }
header h2 { all: unset; flex: 1; font-weight: 600; font-size: 15px; letter-spacing: -0.005em; }
.icon { all: unset; width: 30px; height: 30px; display: grid; place-items: center; border-radius: 6px; color: var(--text-2); cursor: pointer; }
.icon svg { width: 18px; height: 18px; }
@media (hover: hover) { .icon:hover { background: var(--soft); color: var(--text); } }
.log { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 14px; overscroll-behavior: contain; }
.msg { max-width: 100%; overflow-wrap: anywhere; }
.msg.user {
  align-self: flex-end; max-width: 85%; background: var(--accent); color: var(--on-accent);
  padding: 8px 12px; border-radius: 10px 10px 2px 10px; white-space: pre-wrap;
}
.msg.bot p { margin: 0 0 8px; } .msg.bot p:last-child { margin-bottom: 0; }
.msg.bot ul, .msg.bot ol { margin: 4px 0 8px; padding-left: 20px; }
.msg.bot li { margin: 2px 0; }
.msg.bot strong { font-weight: 600; }
.msg.bot a { color: inherit; text-decoration-color: var(--text-3); text-underline-offset: 2px; }
.cite {
  all: unset; display: inline-grid; place-items: center; min-width: 17px; height: 17px; padding: 0 4px; margin: 0 1px;
  font-size: 11px; font-weight: 600; line-height: 1; vertical-align: 1px; font-variant-numeric: tabular-nums;
  border-radius: 4px; background: var(--soft); color: var(--text-2); border: 1px solid var(--line); cursor: default;
}
.cite.on, .src.on .n { background: var(--accent); color: var(--on-accent); border-color: var(--accent); }
.srcs { margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--line); font-size: 12.5px; color: var(--text-2); }
.srcs b { display: block; font-weight: 600; font-size: 12px; color: var(--text-3); margin-bottom: 4px; }
.src { display: flex; gap: 8px; align-items: baseline; padding: 3px 4px; margin: 0 -4px; border-radius: 5px; }
.src.on { background: var(--soft); color: var(--text); }
.src .n { flex: none; min-width: 17px; height: 17px; display: inline-grid; place-items: center; font-size: 11px; font-weight: 600;
  border-radius: 4px; border: 1px solid var(--line); font-variant-numeric: tabular-nums; }
.src a, .src span { color: inherit; text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.src a:hover { text-decoration: underline; }
.wait { color: var(--text-3); display: flex; align-items: center; gap: 8px; animation: fade 200ms 300ms both; }
.dots { display: inline-flex; gap: 3px; }
.dots i { width: 5px; height: 5px; border-radius: 50%; background: currentColor; animation: pulse 1.2s infinite both; }
.dots i:nth-child(2) { animation-delay: .15s; } .dots i:nth-child(3) { animation-delay: .3s; }
@keyframes pulse { 0%, 80%, 100% { opacity: .25 } 40% { opacity: 1 } }
@keyframes fade { from { opacity: 0 } }
.err { background: var(--err-bg); color: var(--text); border-radius: 8px; padding: 10px 12px; font-size: 13.5px; }
.err button { all: unset; display: inline-block; margin-top: 8px; font-weight: 600; color: var(--err); cursor: pointer; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { all: unset; cursor: pointer; padding: 6px 10px; border-radius: 6px; border: 1px solid var(--line); color: var(--text); font-size: 13px; }
@media (hover: hover) { .chip:hover { background: var(--soft); } }
.chip:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
form { display: flex; align-items: flex-end; gap: 6px; padding: 10px; border-top: 1px solid var(--line); }
textarea {
  all: unset; flex: 1; min-height: 20px; max-height: 120px; padding: 8px 10px; border-radius: 8px;
  background: var(--soft); color: var(--text); font: inherit; white-space: pre-wrap; overflow-y: hidden; resize: none;
}
textarea::placeholder { color: var(--text-3); }
.send { all: unset; width: 36px; height: 36px; display: grid; place-items: center; border-radius: 8px; cursor: pointer;
  background: var(--accent); color: var(--on-accent); }
.send:disabled { opacity: .4; cursor: default; }
.send svg { width: 18px; height: 18px; }
.note { padding: 0 12px 10px; font-size: 11.5px; line-height: 1.4; color: var(--text-3); }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
@media (max-width: 480px) {
  .w.open { inset: 0; }
  .w.open .launch { display: none; }
  .panel { position: fixed; inset: 0; width: auto; height: 100%; border-radius: 0; border: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .panel, .w.open .panel, .launch { transition: opacity 120ms; transform: none !important; }
  .dots i { animation: none; opacity: .6; }
}
</style>
<div class="w${cfg.theme === "light" ? " light" : ""}">
  <section class="panel" role="dialog" aria-modal="false" aria-labelledby="ab-title">
    <header>
      <h2 id="ab-title"></h2>
      <button class="icon" data-act="clear" type="button"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/></svg></button>
      <button class="icon" data-act="close" type="button"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
    </header>
    <div class="log" aria-live="polite"></div>
    <form>
      <label class="sr" for="ab-q"></label>
      <textarea id="ab-q" rows="1" maxlength="2000"></textarea>
      <button class="send" type="submit" disabled><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg></button>
    </form>
    <p class="note"></p>
  </section>
  <button class="launch" type="button" aria-expanded="false"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-4.5 4v-4h0A1.5 1.5 0 0 1 4 14.5z"/><path d="M9 8.5h6M9 11.5h4"/></svg></button>
</div>`;

  const $ = (s) => root.querySelector(s);
  const w = $(".w"), log = $(".log"), form = $("form"), input = $("textarea"), send = $(".send"), launch = $(".launch");
  $("#ab-title").textContent = t.title;
  $("label").textContent = t.placeholder;
  input.placeholder = t.placeholder;
  send.setAttribute("aria-label", t.send);
  $(".note").textContent = t.powered;
  $('[data-act="close"]').setAttribute("aria-label", t.close);
  $('[data-act="clear"]').setAttribute("aria-label", t.clear);
  $('[data-act="clear"]').title = t.clear;
  launch.setAttribute("aria-label", t.open);

  let history = [];
  try { history = JSON.parse(sessionStorage.getItem(storeKey) || "[]"); } catch { history = []; }
  let busy = false;

  const esc = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // small, safe markdown: escape first, then add the few things support answers use
  function render(md) {
    const inline = (s) => esc(s)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
      .replace(/\[(\d{1,2})\]/g, '<span class="cite" data-n="$1">$1</span>');
    const out = [];
    let list = null;
    for (const line of md.split("\n")) {
      const m = line.match(/^\s*(?:[-*•]|(\d+)[.)])\s+(.*)$/);
      if (m) {
        const tag = m[1] ? "ol" : "ul";
        if (!list || list.tag !== tag) { if (list) out.push(`</${list.tag}>`); list = { tag }; out.push(`<${tag}>`); }
        out.push(`<li>${inline(m[2])}</li>`);
        continue;
      }
      if (list) { out.push(`</${list.tag}>`); list = null; }
      if (line.trim()) out.push(`<p>${inline(line)}</p>`);
    }
    if (list) out.push(`</${list.tag}>`);
    return out.join("");
  }

  function sourcesBlock(sources, text) {
    const used = new Set([...text.matchAll(/\[(\d{1,2})\]/g)].map((m) => Number(m[1])));
    const shown = sources.filter((s) => used.has(s.n));
    if (!shown.length) return "";
    const rows = shown.map((s) => {
      const label = esc(s.heading && s.heading !== s.title ? `${s.title} · ${s.heading}` : s.title);
      const link = /^https?:\/\//.test(s.source)
        ? `<a href="${esc(s.source)}" target="_blank" rel="noopener">${label}</a>` : `<span>${label}</span>`;
      return `<div class="src" data-n="${s.n}"><span class="n">${s.n}</span>${link}</div>`;
    }).join("");
    return `<div class="srcs"><b>${t.sources}</b>${rows}</div>`;
  }

  function bubble(role, html) {
    const el = document.createElement("div");
    el.className = `msg ${role}`;
    el.innerHTML = html;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  function paint() {
    log.innerHTML = "";
    bubble("bot", render(t.greeting));
    if (!history.length && suggestions.length) {
      const chips = document.createElement("div");
      chips.className = "chips";
      for (const q of suggestions) {
        const b = document.createElement("button");
        b.type = "button"; b.className = "chip"; b.textContent = q;
        b.onclick = () => ask(q);
        chips.appendChild(b);
      }
      log.appendChild(chips);
    }
    for (const m of history) {
      if (m.role === "user") bubble("user", esc(m.content));
      else bubble("bot", render(m.content) + sourcesBlock(m.sources || [], m.content));
    }
  }

  const save = () => { try { sessionStorage.setItem(storeKey, JSON.stringify(history.slice(-30))); } catch {} };

  function setOpen(open) {
    w.classList.toggle("open", open);
    launch.setAttribute("aria-expanded", String(open));
    if (open) { if (!log.childElementCount) paint(); setTimeout(() => input.focus(), 50); log.scrollTop = log.scrollHeight; }
    else launch.focus();
  }

  async function ask(question) {
    question = question.trim();
    if (!question || busy) return;
    busy = true; send.disabled = true;
    root.querySelector(".chips")?.remove();
    history.push({ role: "user", content: question });
    save();
    bubble("user", esc(question));
    const el = bubble("bot", `<div class="wait"><span class="dots"><i></i><i></i><i></i></span>${t.thinking}</div>`);
    let text = "", sources = [], failed = null;

    try {
      const res = await fetch(`${api}/api/chat`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: history.map(({ role, content }) => ({ role, content })).slice(-12) }),
      });
      if (res.status === 429) throw Object.assign(new Error(), { kind: "limited" });
      if (!res.ok || !res.body) throw new Error();
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += value;
        let cut;
        while ((cut = buf.indexOf("\n\n")) >= 0) {
          const raw = buf.slice(0, cut); buf = buf.slice(cut + 2);
          const type = /^event: (.*)$/m.exec(raw)?.[1];
          const data = JSON.parse(/^data: (.*)$/m.exec(raw)?.[1] ?? "null");
          if (type === "sources") sources = data;
          else if (type === "delta") { text += data; el.innerHTML = render(text); log.scrollTop = log.scrollHeight; }
          else if (type === "error") failed = "unavailable";
        }
      }
      if (!text && !failed) failed = "unavailable";
    } catch (e) {
      failed = e.kind || (navigator.onLine === false ? "offline" : "unavailable");
    }

    if (failed) {
      history.pop(); save();
      el.innerHTML = `<div class="err">${t[failed]}<br><button type="button">${t.retry}</button></div>`;
      el.querySelector("button").onclick = () => { el.previousElementSibling?.remove(); el.remove(); busy = false; ask(question); };
    } else {
      el.innerHTML = render(text) + sourcesBlock(sources, text);
      history.push({ role: "assistant", content: text, sources });
      save();
    }
    busy = false;
    send.disabled = !input.value.trim();
    log.scrollTop = log.scrollHeight;
  }

  // hovering a citation lights up its source, and the other way round
  root.addEventListener("pointerover", (e) => {
    const hit = e.target.closest?.("[data-n]");
    const msg = e.target.closest?.(".msg");
    root.querySelectorAll(".on").forEach((n) => n.classList.remove("on"));
    if (hit && msg) msg.querySelectorAll(`[data-n="${hit.dataset.n}"]`).forEach((n) => n.classList.add("on"));
  });

  launch.onclick = () => setOpen(!w.classList.contains("open"));
  $('[data-act="close"]').onclick = () => setOpen(false);
  $('[data-act="clear"]').onclick = () => { history = []; save(); paint(); input.focus(); };
  input.addEventListener("input", () => {
    send.disabled = busy || !input.value.trim();
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
    // only show a scrollbar once the text is taller than the box can grow
    input.style.overflowY = input.scrollHeight > 120 ? "auto" : "hidden";
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  });
  root.addEventListener("keydown", (e) => { if (e.key === "Escape" && w.classList.contains("open")) setOpen(false); });
  form.onsubmit = (e) => {
    e.preventDefault();
    const q = input.value;
    input.value = ""; input.style.height = "auto"; send.disabled = true;
    ask(q);
  };

  (document.body || document.documentElement).appendChild(host);
  if (cfg.open === "true") setOpen(true);

  // lets the host page open the assistant or link an FAQ straight to a question
  window.askbase = {
    open: () => setOpen(true),
    close: () => setOpen(false),
    ask: (q) => { setOpen(true); ask(String(q)); },
  };
})();
