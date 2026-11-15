"""Navigation: category drill-down, load-more, post chains, redirects, site search, SPA routes, broken links, tabs."""
from evals.bench.core import PAGES, REDIRECTS, answer, bench, shell, want


async def _ret(v):
    return v


# 39 category drill-down through four levels
TREE = {"": ["Electronics", "Home", "Fashion", "Books"], "electronics": ["Phones", "Audio", "Cameras", "Laptops"],
        "audio": ["Speakers", "Headphones", "Microphones"], "headphones": ["Sonic X1", "Sonic X2", "Sonic X2 Pro", "Pulse Buds"]}
SKU = {"Sonic X1": "SX1-2208-WHT", "Sonic X2": "SX2-4471-BLK", "Sonic X2 Pro": "SX2P-9930-GRY", "Pulse Buds": "PB-1102-BLU"}
_slug = lambda s: s.lower().replace(" ", "-")
for _k, _items in TREE.items():
    _path = "/b/store/" + (_k + ".html" if _k else "index.html")
    _hrefs = [f"/b/store/{'p-' if _k == 'headphones' else ''}{_slug(i)}.html" for i in _items]
    PAGES[_path] = shell("Store", f"<main><h1>{_k.title() or 'Store'}</h1><ul>" + "".join(
        f"<li><a href='{h}'>{i}</a></li>" for h, i in zip(_hrefs, _items)) + "</ul></main>")
for _n, _sku in SKU.items():
    PAGES[f"/b/store/p-{_slug(_n)}.html"] = shell(_n, f"<main><h1>{_n}</h1><p>Wireless headphones.</p><p>SKU: {_sku}</p></main>")
bench("store-drill", "/b/store/index.html", "Find the SKU of the Sonic X2 headphones (not the Pro) in the store.",
      answer("sx2-4471-blk"), lambda p, b: _ret("SX2-4471-BLK"), ("navigate", "hierarchy"))

# 40 "Load more" button (fetch-appended items)
ITEMS = [f"{a} {b}" for a in ("Copper", "Walnut", "Indigo", "Saffron", "Ivory", "Slate") for b in
         ("mug", "lamp", "throw", "vase", "clock")]
PAGES["/b/api/catalog"] = lambda q: (__import__("json").dumps(
    [{"n": i + 1, "name": ITEMS[i]} for i in range(int(q.get("offset", 0)), min(int(q.get("offset", 0)) + 10, len(ITEMS)))]).encode(), "application/json")
bench("load-more", "/b/catalog.html", "What is the name of item #27 in the catalogue?",
      answer(ITEMS[26].lower()), lambda p, b: _ret(ITEMS[26]), ("navigate", "load-more"),
      shell("Catalogue", "<main><h1>Catalogue</h1><ol id='l'></ol><button id='more'>Load more</button></main>",
            """let off = 0; const load = async () => { const r = await (await fetch('/b/api/catalog?offset=' + off)).json();
  r.forEach(x => { const li = document.createElement('li'); li.textContent = `#${x.n} ${x.name}`; document.getElementById('l').appendChild(li); });
  off += r.length; if (off >= 30) document.getElementById('more').remove(); };
document.getElementById('more').onclick = load; load();"""))

# 41 follow a "Next post" chain
POSTS = ["Monsoon packing list", "Learning Rust in 30 days", "Why I switched to a standing desk", "A week without social media",
         "Notes from PyCon India", "Baking sourdough at altitude", "My home lab setup", "Reading 50 books a year"]
for _i, _t in enumerate(POSTS):
    _prev = f"<a href='/b/blog/{_i}.html'>← Previous post</a>" if _i else ""
    _next = f"<a href='/b/blog/{_i + 2}.html'>Next post →</a>" if _i + 1 < len(POSTS) else ""
    PAGES[f"/b/blog/{_i + 1}.html"] = shell(_t, f"<main><article><h1>{_t}</h1><p>Post {_i + 1}. Some thoughts.</p></article>"
                                                f"<nav aria-label='Post navigation'>{_prev} {_next}</nav></main>")
PAGES["/b/blog/index.html"] = shell("Blog", "<main><h1>Blog</h1><ul>" + "".join(
    f"<li><a href='/b/blog/{i + 1}.html'>{t}</a></li>" for i, t in reversed(list(enumerate(POSTS)))) + "</ul></main>")
bench("blog-next", "/b/blog/index.html",
      "Open the post 'Learning Rust in 30 days', then follow its 'Next post' link twice. What is the title of the post you end up on?",
      answer("a week without social media"), lambda p, b: _ret(POSTS[3]), ("navigate", "links"))

# 42 redirects, then a platform-specific value
PAGES["/b/downloads.html"] = shell("Downloads", """<main><h1>Download centre</h1><table><tr><th>Platform</th><th>Version</th></tr>
<tr><td>Windows</td><td>4.12.3</td></tr><tr><td>macOS</td><td>4.12.1</td></tr><tr><td>Linux</td><td>4.11.9</td></tr></table></main>""")
PAGES["/b/app-home.html"] = shell("NoteKit", "<main><h1>NoteKit</h1><p>Notes that sync.</p><a href='/b/go/downloads'>Download centre</a></main>")
REDIRECTS.update({"/b/go/downloads": "/b/go/dl-v2", "/b/go/dl-v2": "/b/downloads.html"})
bench("redirects", "/b/app-home.html", "What is the current macOS version listed in NoteKit's download centre?",
      answer("4.12.1"), lambda p, b: _ret("4.12.1"), ("navigate", "redirect"))

# 43 site search in a help centre
HELP = {"warranty-new": ("Warranty for new devices", "New devices carry a 12 month warranty from the invoice date."),
        "warranty-refurb": ("Warranty for refurbished devices", "Refurbished devices carry a 6 month warranty."),
        "shipping": ("Shipping times", "Orders ship within 2 days."), "returns": ("Returns", "Return within 10 days.")}
for _k, (_t, _b) in HELP.items():
    PAGES[f"/b/help/{_k}.html"] = shell(_t, f"<main><h1>{_t}</h1><p>{_b}</p></main>")


def _help_search(q):
    term = q.get("q", "").lower()
    hits = [(k, t) for k, (t, b) in HELP.items() if term and (term in t.lower() or term in b.lower())]
    rows = "".join(f"<li><a href='/b/help/{k}.html'>{t}</a></li>" for k, t in hits)
    return shell("Help search", f"<main><h1>Help centre</h1><form action='/b/help/search'><input name='q' aria-label='Search help' value='{term}'>"
                                f"<button>Search</button></form>{f'<ul>{rows}</ul>' if term else ''}</main>")


PAGES["/b/help/search"] = _help_search
PAGES["/b/help/index.html"] = shell("Help centre", "<main><h1>Help centre</h1><form action='/b/help/search'>"
                                                   "<input name='q' aria-label='Search help'><button>Search</button></form><p>Popular: shipping, returns.</p></main>")
bench("help-search", "/b/help/index.html", "Using the help centre search, find how long the warranty on refurbished devices is.",
      answer(r"\b6\b", "month", regex=True), lambda p, b: _ret("6 months"), ("navigate", "search"))

# 44 hash-routed admin SPA with in-app pagination
USERS = [(i + 1, n, f"{n.split()[0].lower()}.{n.split()[1][0].lower()}{i + 1}@corp.example") for i, n in enumerate(
    ["Aarav Shah", "Bela Nair", "Chetan Rao", "Diya Kapoor", "Eshan Gill", "Fatima Sheikh", "Gaurav Jain", "Hina Qureshi",
     "Ishaan Dutta", "Jaya Pillai", "Kabir Sethi", "Lata Menon", "Manav Arora", "Neha Bose", "Om Prakash", "Pooja Das",
     "Kiran Bhat", "Rhea Sen", "Sahil Khan", "Tara Iyer", "Uday Joshi", "Vani Reddy", "Kiran Bedi", "Yash Malhotra"])]
KIRAN = next(u for u in USERS if u[1] == "Kiran Bhat")
bench("admin-spa", "/b/admin.html", "Find the email address of the user Kiran Bhat in the admin panel.",
      answer(KIRAN[2]), lambda p, b: _ret(KIRAN[2]), ("navigate", "spa"),
      shell("Admin", "<main><h1>Admin</h1><div id='v'></div></main>",
            "const U = " + str([list(u) for u in USERS]).replace("'", '"') + """;
const render = () => { const h = location.hash || '#/users?page=1'; const v = document.getElementById('v'); let m;
  if ((m = h.match(/^#\\/users\\/(\\d+)/))) { const u = U.find(x => x[0] == m[1]);
    v.innerHTML = `<h2>${u[1]}</h2><p>Email: ${u[2]}</p><p>Role: member</p><a href='#/users?page=1'>All users</a>`; return; }
  const p = +((h.match(/page=(\\d+)/) || [])[1] || 1);
  v.innerHTML = '<h2>Users</h2><ul>' + U.slice((p - 1) * 8, p * 8).map(u => `<li><a href='#/users/${u[0]}'>${u[1]}</a></li>`).join('') + '</ul>'
    + `<p>Page ${p} of 3 ${p > 1 ? `<a href='#/users?page=${p - 1}'>Previous</a>` : ''} ${p < 3 ? `<a href='#/users?page=${p + 1}'>Next</a>` : ''}</p>`; };
window.addEventListener('hashchange', render); render();"""))

# 45 the obvious link is broken
PAGES["/b/acme.html"] = shell("Acme", """<main><h1>Acme Appliances</h1><nav aria-label='Main'><a href='/b/support-old.html'>Support</a>
<a href='/b/acme-products.html'>Products</a></nav><p>Quality appliances since 1987.</p></main>
<section><a href='/b/helpdesk.html'>Help centre</a> · <a href='/b/acme-careers.html'>Careers</a></section>""")
PAGES["/b/helpdesk.html"] = shell("Acme help centre", "<main><h1>Help centre</h1><p>Call customer support on 1800-200-3344 (9 am–9 pm).</p></main>")
bench("broken-link", "/b/acme.html", "Find Acme's customer support phone number.",
      answer("1800-200-3344"), lambda p, b: _ret("1800-200-3344"), ("navigate", "404"))

# 46 read a value in a new tab, use it on the original page
PAGES["/b/terms.html"] = shell("Terms of service", "<main><h1>Terms of service</h1><p>Version 3.2, effective 1 October 2026.</p><p>Be nice.</p></main>")
bench("terms-version", "/b/accept-terms.html",
      "Accept the terms of service, entering the terms version shown on the terms page.",
      want("terms", agree="on", version="3.2"), lambda p, b: _terms(p), ("tabs", "form"),
      shell("Accept terms", """<main><h1>Before you continue</h1><p><a href='/b/terms.html' target='_blank'>Read the terms of service</a> (opens in a new tab)</p>
<form method='post' action='/api/submit/terms'><label><input type='checkbox' name='agree'> I have read and accept the terms</label>
<label>Terms version you accepted <input name='version'></label><button type='submit'>Continue</button></form></main>"""))


async def _terms(p):
    async with p.context.expect_page() as pi:
        await p.click("text=Read the terms of service")
    t = await pi.value
    await t.wait_for_load_state()
    ver = (await t.inner_text("main")).split("Version ")[1].split(",")[0]
    await t.close()
    await p.check("[name=agree]")
    await p.fill("[name=version]", ver)
    await p.click("button[type=submit]")
    await p.wait_for_selector("text=submission received")
    return ""

