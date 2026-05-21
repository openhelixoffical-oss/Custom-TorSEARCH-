"""
tor_search.py — Tor .onion search engine, single file version.

Requirements:
    pip install requests[socks] beautifulsoup4

Make sure Tor is running (SOCKS5 on 127.0.0.1:9050) before crawling.
"""

import sqlite3
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import sys, os, time
from collections import deque
from urllib.parse import urljoin, urlparse

DB_PATH = "tor_index.db"

# ── Crawler ───────────────────────────────────────────────────────────────────

TOR_PROXY = {
    "http":  "socks5h://127.0.0.1:9050",
    "https": "socks5h://127.0.0.1:9050",
}
REQUEST_TIMEOUT = 40
CRAWL_DELAY     = 3
MAX_PAGES       = 500
MAX_QUEUE       = 2000


def is_onion(url):
    host = urlparse(url).netloc.lower()
    return host.endswith(".onion") or ".onion:" in host


def clean_text(soup):
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return " ".join(soup.get_text(separator=" ").split())


def extract_links(soup, base_url):
    links = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if href.startswith(("javascript:", "mailto:", "#")):
            continue
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if parsed.scheme in ("http", "https") and is_onion(full):
            clean = parsed._replace(fragment="").geturl()
            links.append(clean)
    return links


def crawl(seed_urls, db_path, status_callback=None, should_stop=None):
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        if status_callback:
            status_callback("ERROR: Run: pip install requests[socks] beautifulsoup4", "error")
        return

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS visited (url TEXT PRIMARY KEY)")
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS pages USING fts5(
            url, title, body, tokenize='porter ascii'
        )
    """)
    conn.commit()

    def is_visited(url):
        return conn.execute("SELECT 1 FROM visited WHERE url=?", (url,)).fetchone() is not None

    def mark_visited(url):
        conn.execute("INSERT OR IGNORE INTO visited (url) VALUES (?)", (url,))
        conn.commit()

    def save_page(url, title, body):
        conn.execute("DELETE FROM pages WHERE url=?", (url,))
        conn.execute("INSERT INTO pages (url, title, body) VALUES (?, ?, ?)",
                     (url, title, body[:50000]))
        conn.commit()

    def count():
        return conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]

    def log(msg, tag="info"):
        if status_callback:
            status_callback(msg, tag)

    queue = deque(seed_urls)
    queued_set = set(seed_urls)

    session = requests.Session()
    session.proxies.update(TOR_PROXY)
    session.headers.update({"User-Agent": "TorSearchBot/1.0"})

    log("Crawl started. Seeds: " + str(len(seed_urls)), "good")

    while queue:
        if should_stop and should_stop():
            log("Stopped.", "dim")
            break

        url = queue.popleft()
        if is_visited(url):
            continue

        n = count()
        if n >= MAX_PAGES:
            log("Reached max pages. Stopping.")
            break

        log("[" + str(n) + "/" + str(MAX_PAGES) + "] Fetching: " + url)
        mark_visited(url)

        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            ct = resp.headers.get("Content-Type", "")
            if "text/html" not in ct:
                log("  Skipping non-HTML", "dim")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            title = (soup.title.string.strip()
                     if soup.title and soup.title.string else url)
            body = clean_text(soup)

            if len(body) < 50:
                log("  Skipping (too little text)", "dim")
                continue

            save_page(url, title, body)
            log("  Indexed: " + title[:60], "good")

            new_links = extract_links(soup, url)
            added = 0
            for link in new_links:
                if link not in queued_set and not is_visited(link):
                    if len(queue) < MAX_QUEUE:
                        queue.append(link)
                        queued_set.add(link)
                        added += 1
            if added:
                log("  Added " + str(added) + " links (queue: " + str(len(queue)) + ")", "dim")

        except Exception as e:
            log("  Error: " + str(e), "error")

        time.sleep(CRAWL_DELAY)

    conn.close()
    log("Crawl complete.", "good")


# ── DB helpers ────────────────────────────────────────────────────────────────

def ensure_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS visited (url TEXT PRIMARY KEY)")
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS pages USING fts5(
            url, title, body, tokenize='porter ascii'
        )
    """)
    conn.commit()
    conn.close()


def search_index(query, limit=50):
    if not query.strip():
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT url, title,
                   snippet(pages, 2, '**', '**', '...', 32) AS snippet,
                   rank
            FROM pages WHERE pages MATCH ?
            ORDER BY rank LIMIT ?
        """, (query, limit)).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def indexed_count():
    try:
        conn = sqlite3.connect(DB_PATH)
        n = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


# ── Colours ───────────────────────────────────────────────────────────────────

C_WIN        = "#f0f0f0"
C_TOOLBAR    = "#dee1e6"
C_TOOLBAR_B  = "#c8cbd0"
C_ADDRBAR    = "#ffffff"
C_ADDRBAR_BD = "#a0a4aa"
C_ADDRBAR_FO = "#0060df"
C_PAGE       = "#ffffff"
C_TAB_ACT    = "#ffffff"
C_TAB_IN     = "#d0d3d8"
C_TAB_TXT    = "#1a1a1a"
C_TITLE      = "#0060df"
C_URL        = "#006621"
C_SNIPPET    = "#1a1a1a"
C_DIM        = "#6b7280"
C_BTN        = "#0060df"
C_LOG_BG     = "#1e1e1e"
C_LOG_TXT    = "#d4d4d4"
C_GREEN      = "#1a7f37"
C_RED        = "#cf222e"
C_BORDER     = "#c8cbd0"

FONT_UI      = ("Segoe UI", 10)
FONT_SMALL   = ("Segoe UI", 9)
FONT_ADDR    = ("Segoe UI", 11)
FONT_TITLE   = ("Segoe UI", 11, "bold")
FONT_SNIPPET = ("Segoe UI", 10)
FONT_URL     = ("Segoe UI", 9)
FONT_MONO    = ("Consolas", 9)
FONT_CHROME  = ("Segoe UI", 9)


# ── Main app ──────────────────────────────────────────────────────────────────

class TorSearchApp(tk.Tk):
    def __init__(self):
        super().__init__()
        ensure_db()
        self.title("TorSearch")
        self.configure(bg=C_WIN)
        self.geometry("900x700")
        self.minsize(720, 500)
        self._crawler_running = False
        self._build_ui()
        self._refresh_count()

    def _build_ui(self):
        self._build_titlebar()
        self._build_toolbar()
        self._build_pages()
        self._build_results_area()
        self._build_crawler_area()
        self._build_statusbar()

    def _build_titlebar(self):
        bar = tk.Frame(self, bg=C_TOOLBAR, height=36)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        self._tab_results = tk.Label(
            bar, text="   TorSearch  x  ", font=FONT_CHROME,
            bg=C_TAB_ACT, fg=C_TAB_TXT, relief="flat", padx=4, pady=8, cursor="hand2")
        self._tab_results.pack(side="left", padx=(8, 0), pady=(4, 0), ipady=2)
        self._tab_results.bind("<Button-1>", lambda _: self._show_results())

        self._tab_crawler = tk.Label(
            bar, text="   Crawler  x  ", font=FONT_CHROME,
            bg=C_TAB_IN, fg=C_DIM, relief="flat", padx=4, pady=8, cursor="hand2")
        self._tab_crawler.pack(side="left", padx=(2, 0), pady=(4, 0), ipady=2)
        self._tab_crawler.bind("<Button-1>", lambda _: self._show_crawler())

        tk.Label(bar, text=" + ", font=FONT_CHROME,
                 bg=C_TOOLBAR, fg=C_DIM).pack(side="left", pady=8)

        tk.Label(bar, text="by brad", font=("Segoe UI", 8, "italic"),
                 bg=C_TOOLBAR, fg=C_DIM).pack(side="right", padx=(0, 8))

        self._count_lbl = tk.Label(bar, text="", font=FONT_CHROME,
                                   bg=C_TOOLBAR, fg=C_DIM)
        self._count_lbl.pack(side="right", padx=12)

    def _build_toolbar(self):
        bar = tk.Frame(self, bg=C_TOOLBAR,
                       highlightbackground=C_TOOLBAR_B, highlightthickness=1)
        bar.pack(fill="x", ipady=5)

        for sym in ["<", ">", "~"]:
            tk.Label(bar, text=sym, font=("Segoe UI", 13),
                     bg=C_TOOLBAR, fg=C_DIM, width=2).pack(side="left", padx=4)

        addr_outer = tk.Frame(bar, bg=C_ADDRBAR,
                              highlightbackground=C_ADDRBAR_BD, highlightthickness=1)
        addr_outer.pack(side="left", fill="x", expand=True, padx=8, pady=3)

        tk.Label(addr_outer, text="[tor]", font=("Segoe UI", 8),
                 bg=C_ADDRBAR, fg=C_DIM).pack(side="left", padx=(6, 2))

        self._query_var = tk.StringVar()
        entry = tk.Entry(addr_outer, textvariable=self._query_var,
                         font=FONT_ADDR, bg=C_ADDRBAR, fg="#1a1a1a",
                         insertbackground="#1a1a1a", relief="flat", bd=0)
        entry.pack(side="left", fill="x", expand=True, ipady=4)
        entry.bind("<Return>", lambda _: self._do_search())
        entry.bind("<FocusIn>",  lambda _: addr_outer.config(
            highlightbackground=C_ADDRBAR_FO, highlightthickness=2))
        entry.bind("<FocusOut>", lambda _: addr_outer.config(
            highlightbackground=C_ADDRBAR_BD, highlightthickness=1))
        entry.focus()

        tk.Button(addr_outer, text="Search", command=self._do_search,
                  font=FONT_CHROME, bg=C_BTN, fg="white",
                  activebackground="#0050c0", relief="flat",
                  padx=12, pady=3, cursor="hand2", bd=0).pack(
                      side="right", padx=4, pady=2)

        tk.Label(bar, text="...", font=("Segoe UI", 14),
                 bg=C_TOOLBAR, fg=C_DIM, cursor="hand2").pack(side="right", padx=8)

    def _build_pages(self):
        self._page_container = tk.Frame(self, bg=C_PAGE)
        self._page_container.pack(fill="both", expand=True)
        self._results_page = tk.Frame(self._page_container, bg=C_PAGE)
        self._crawler_page = tk.Frame(self._page_container, bg=C_WIN)
        self._results_page.place(relwidth=1, relheight=1)

    def _build_results_area(self):
        p = self._results_page
        tk.Frame(p, bg=C_BORDER, height=1).pack(fill="x")
        self._info_lbl = tk.Label(p,
            text="Type a search query in the address bar above and press Enter",
            font=("Segoe UI", 9), fg=C_DIM, bg=C_PAGE, anchor="w")
        self._info_lbl.pack(fill="x", padx=20, pady=(6, 2))
        tk.Frame(p, bg=C_BORDER, height=1).pack(fill="x")

        outer = tk.Frame(p, bg=C_PAGE)
        outer.pack(fill="both", expand=True)

        self._canvas = tk.Canvas(outer, bg=C_PAGE, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=self._canvas.yview)
        self._inner = tk.Frame(self._canvas, bg=C_PAGE)
        self._inner.bind("<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._canvas.bind_all("<MouseWheel>",
            lambda e: self._canvas.yview_scroll(-1*(e.delta//120), "units"))

    def _build_crawler_area(self):
        p = self._crawler_page
        tk.Frame(p, bg=C_BORDER, height=1).pack(fill="x")

        tk.Label(p, text="Web Crawler", font=("Segoe UI", 12, "bold"),
                 fg="#1a1a1a", bg=C_WIN).pack(anchor="w", padx=20, pady=(10, 4))

        seed_frame = tk.Frame(p, bg=C_WIN)
        seed_frame.pack(fill="x", padx=20, pady=(0, 6))
        tk.Label(seed_frame, text="Seed .onion URLs (one per line):",
                 font=FONT_SMALL, fg=C_DIM, bg=C_WIN).pack(anchor="w")
        self._seed_box = scrolledtext.ScrolledText(
            seed_frame, font=FONT_MONO, bg=C_ADDRBAR, fg="#1a1a1a",
            relief="solid", bd=1, height=5, wrap="none")
        self._seed_box.pack(fill="x", pady=(2, 0))
        self._seed_box.insert("1.0",
            "http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion\n"
            "http://haystak5njsmn2hqkewecpaxetahtwhsbsa64jom2k22z5afxhnpxfid.onion\n")

        btn_row = tk.Frame(p, bg=C_WIN)
        btn_row.pack(fill="x", padx=20, pady=8)

        self._crawl_btn = tk.Button(btn_row, text="Start Crawl",
            command=self._start_crawl, font=FONT_UI, bg=C_BTN, fg="white",
            activebackground="#0050c0", relief="flat", padx=14, pady=5, cursor="hand2")
        self._crawl_btn.pack(side="left")

        self._stop_btn = tk.Button(btn_row, text="Stop",
            command=self._stop_crawl, font=FONT_UI, bg="#e3e3e3", fg=C_DIM,
            relief="flat", padx=14, pady=5, cursor="hand2", state="disabled")
        self._stop_btn.pack(side="left", padx=(8, 0))

        self._crawl_status = tk.Label(btn_row, text="", font=FONT_SMALL,
                                      fg=C_DIM, bg=C_WIN)
        self._crawl_status.pack(side="left", padx=12)

        tk.Label(p, text="Console", font=FONT_SMALL, fg=C_DIM, bg=C_WIN
                 ).pack(anchor="w", padx=20)
        self._log_box = scrolledtext.ScrolledText(
            p, font=FONT_MONO, bg=C_LOG_BG, fg=C_LOG_TXT,
            state="disabled", relief="flat", bd=0,
            highlightbackground=C_BORDER, highlightthickness=1)
        self._log_box.pack(fill="both", expand=True, padx=20, pady=(2, 12))
        self._log_box.tag_config("good",  foreground="#4ec9b0")
        self._log_box.tag_config("error", foreground="#f48771")
        self._log_box.tag_config("dim",   foreground="#808080")

    def _build_statusbar(self):
        sb = tk.Frame(self, bg=C_TOOLBAR,
                      highlightbackground=C_TOOLBAR_B, highlightthickness=1, height=22)
        sb.pack(fill="x", side="bottom")
        sb.pack_propagate(False)
        self._status_lbl = tk.Label(sb, text="", font=("Segoe UI", 8),
                                    fg=C_DIM, bg=C_TOOLBAR, anchor="w")
        self._status_lbl.pack(side="left", padx=8)
        tk.Label(sb, text="Tor  [on]", font=("Segoe UI", 8),
                 fg=C_DIM, bg=C_TOOLBAR).pack(side="right", padx=8)

    def _show_results(self):
        self._crawler_page.place_forget()
        self._results_page.place(relwidth=1, relheight=1)
        self._tab_results.config(bg=C_TAB_ACT, fg=C_TAB_TXT)
        self._tab_crawler.config(bg=C_TAB_IN,  fg=C_DIM)

    def _show_crawler(self):
        self._results_page.place_forget()
        self._crawler_page.place(relwidth=1, relheight=1)
        self._tab_crawler.config(bg=C_TAB_ACT, fg=C_TAB_TXT)
        self._tab_results.config(bg=C_TAB_IN,  fg=C_DIM)

    def _do_search(self):
        query = self._query_var.get().strip()
        if not query:
            return
        self._show_results()
        self._render_results(query, search_index(query))

    def _render_results(self, query, results):
        for w in self._inner.winfo_children():
            w.destroy()

        if not results:
            tk.Label(self._inner, text='No results found for "' + query + '".',
                     font=FONT_SNIPPET, fg=C_DIM, bg=C_PAGE).pack(pady=40, padx=40)
            self._info_lbl.config(text="No results found")
            return

        self._info_lbl.config(
            text="About " + str(len(results)) + " result(s) — searched local .onion index")

        for r in results:
            card = tk.Frame(self._inner, bg=C_PAGE)
            card.pack(fill="x", padx=40, pady=(14, 0))

            url_row = tk.Frame(card, bg=C_PAGE)
            url_row.pack(fill="x")
            tk.Label(url_row, text=r["url"][:80], font=FONT_URL,
                     fg=C_URL, bg=C_PAGE, anchor="w").pack(side="left")
            tk.Button(url_row, text="Copy",
                      command=lambda u=r["url"]: self._copy(u),
                      font=("Segoe UI", 8), bg="#eeeeee", fg=C_DIM,
                      activebackground="#dddddd", relief="flat",
                      padx=6, cursor="hand2", bd=0).pack(side="left", padx=4)

            title = (r.get("title") or r["url"])[:100]
            lbl = tk.Label(card, text=title, font=FONT_TITLE,
                           fg=C_TITLE, bg=C_PAGE, anchor="w", cursor="hand2")
            lbl.pack(fill="x")
            lbl.bind("<Button-1>", lambda _, u=r["url"]: self._copy(u))
            lbl.bind("<Enter>", lambda e: e.widget.config(fg="#003eaa"))
            lbl.bind("<Leave>", lambda e: e.widget.config(fg=C_TITLE))

            snippet = (r.get("snippet") or "")[:220]
            if snippet:
                tk.Label(card, text=snippet, font=FONT_SNIPPET,
                         fg=C_SNIPPET, bg=C_PAGE, anchor="w",
                         wraplength=700, justify="left").pack(fill="x", pady=(2, 0))

            tk.Frame(self._inner, bg=C_BORDER, height=1).pack(
                fill="x", padx=40, pady=(10, 0))

        self._canvas.yview_moveto(0)

    def _copy(self, url):
        self.clipboard_clear()
        self.clipboard_append(url)
        self._status_lbl.config(text="Copied to clipboard: " + url)
        self.after(3000, lambda: self._status_lbl.config(text=""))

    def _start_crawl(self):
        if self._crawler_running:
            return
        raw = self._seed_box.get("1.0", "end")
        seeds = [s.strip() for s in raw.splitlines() if s.strip()]
        if not seeds:
            messagebox.showwarning("No seeds", "Add at least one .onion URL.")
            return

        self._crawler_running = True
        self._crawl_btn.config(state="disabled")
        self._stop_btn.config(state="normal", bg="#ffd7d7", fg=C_RED)
        self._crawl_status.config(text="Crawling...", fg=C_BTN)

        def run():
            crawl(seeds, DB_PATH,
                  status_callback=self._log_ts,
                  should_stop=lambda: not self._crawler_running)
            self._crawler_running = False
            self.after(0, self._crawl_done)

        threading.Thread(target=run, daemon=True).start()

    def _stop_crawl(self):
        self._crawler_running = False
        self._log("Stopping after current request...", "dim")

    def _crawl_done(self):
        self._crawler_running = False
        self._crawl_btn.config(state="normal")
        self._stop_btn.config(state="disabled", bg="#e3e3e3", fg=C_DIM)
        self._crawl_status.config(text="Done", fg=C_GREEN)
        self._log("Crawl complete.", "good")
        self._refresh_count()

    def _log(self, msg, tag="info"):
        self._log_box.config(state="normal")
        self._log_box.insert("end", msg + "\n", tag)
        self._log_box.see("end")
        self._log_box.config(state="disabled")

    def _log_ts(self, msg, tag="info"):
        self.after(0, lambda: self._log(msg, tag))

    def _refresh_count(self):
        n = indexed_count()
        self._count_lbl.config(
            text=str(n) + " pages indexed",
            fg=C_GREEN if n > 0 else C_DIM)
        self.after(5000, self._refresh_count)


if __name__ == "__main__":
    TorSearchApp().mainloop()
