"""Live-site tasks: real public pages, read-only or harmless test endpoints, with answers that rarely
change. Success is judged from the agent's final answer (there is no fixture server to ask), so these
results are reported separately from the fixture suite and labelled "live" — pages and networks vary.
"""
from __future__ import annotations

import re

from evals.tasks import Task


def _has(*needles):
    def v(state, ans):
        low = ans.lower()
        missing = [n for n in needles if n.lower() not in low]
        return (not missing, f"answer missing {missing}" if missing else "ok")
    return v


def _year(y):
    def v(state, ans):
        return (re.search(rf"\b{y}\b", ans) is not None, f"want {y}")
    return v


LIVE_TASKS: list[Task] = [
    Task("live-python-designer", "https://en.wikipedia.org/wiki/Python_(programming_language)",
         "According to this Wikipedia article, who designed the Python programming language?",
         _has("guido van rossum"), ("live", "read")),
    Task("live-halley", "https://en.wikipedia.org/wiki/Halley%27s_Comet",
         "According to this article, in what year did Halley's Comet last reach perihelion?",
         _year(1986), ("live", "read")),
    Task("live-obscura-license", "https://github.com/h4ckf0r0day/obscura",
         "What open-source license is this GitHub repository published under?",
         _has("apache"), ("live", "read")),
    Task("live-example-link", "https://example.com/",
         "Follow the only link on this page and report the domain name of the page it opens.",
         _has("iana"), ("live", "navigate")),
    Task("live-httpbin-form", "https://httpbin.org/forms/post",
         "Fill this test form with customer name 'Lean Tester', telephone '5550100', a small pizza with onion, "
         "submit it, and report the customer name the server echoed back.",
         _has("lean tester"), ("live", "form")),
]

# Interaction coverage on public sandboxes built for automation practice (no logins, no real accounts, no
# purchases). Added 2026-11-21 for the pre-release hardening pass.
TI = "https://the-internet.herokuapp.com"
BOOKS = "https://books.toscrape.com/"
QUOTES = "https://quotes.toscrape.com"
LIVE_TASKS += [
    Task("live-books-price", BOOKS, "What is the price of the book 'A Light in the Attic'?", _has("51.77"), ("live", "read")),
    Task("live-books-travel", BOOKS, "Open the Travel category. How many books does it list?", _has("11"), ("live", "navigate")),
    Task("live-books-page2", BOOKS, "Go to page 2 of the catalogue. What is the title of the first book on it?",
         _has("in her wake"), ("live", "navigate")),
    Task("live-books-links", BOOKS, "Give the titles and full URLs of the first three books on this page.",
         _has("a-light-in-the-attic_1000", "tipping-the-velvet_999", "soumission_998"), ("live", "read")),
    Task("live-quotes-love", QUOTES, "Open the 'love' tag. Who is the author of the first quote shown?",
         _has("andré gide"), ("live", "navigate")),
    Task("live-quotes-js", QUOTES + "/js/", "This page renders quotes with JavaScript. Who wrote the first quote?",
         _has("einstein"), ("live", "dynamic")),
    Task("live-quotes-scroll", QUOTES + "/scroll", "Quotes load as you scroll. Scroll until at least 20 quotes are "
         "loaded and report the author of the 20th quote.", _has("allen saunders"), ("live", "dynamic")),
    Task("live-ti-dropdown", TI + "/dropdown", "Select 'Option 2' in the dropdown and report which option is selected.",
         _has("option 2"), ("live", "widget")),
    Task("live-ti-checkboxes", TI + "/checkboxes", "Make both checkboxes checked, then report the state of each.",
         _has("checked"), ("live", "widget")),
    Task("live-ti-loading", TI + "/dynamic_loading/2", "Start the loading and report the text that appears when it finishes.",
         _has("hello world"), ("live", "dynamic")),
    Task("live-ti-confirm", TI + "/javascript_alerts", "Click the button for a JS Confirm, accept it, and report the result text.",
         _has("you clicked: ok"), ("live", "dialog")),
    Task("live-ti-prompt", TI + "/javascript_alerts", "Click the button for a JS Prompt, answer it with 'lean', and report the result text.",
         _has("you entered: lean"), ("live", "dialog")),
    Task("live-ti-tables", TI + "/tables", "In Example 1, which person has the largest amount due? Give the full name.",
         _has("jason", "doe"), ("live", "read")),
    Task("live-ti-hover", TI + "/hovers", "Hover over the first user picture and report the user name it reveals.",
         _has("user1"), ("live", "widget")),
    Task("live-ti-add", TI + "/add_remove_elements/", "Click 'Add Element' three times, then delete one. How many Delete buttons remain?",
         _has("2"), ("live", "widget")),
    Task("live-ti-window", TI + "/windows", "Click the link that opens a new window and report the heading on the new page.",
         _has("new window"), ("live", "tabs")),
    Task("live-ti-frames", TI + "/nested_frames", "This page has nested frames. What text does the middle frame show?",
         _has("middle"), ("live", "frames")),
    Task("live-ti-iframe-editor", TI + "/iframe", "What text does the rich-text editor contain right now?",
         _has("your content goes here"), ("live", "frames")),
    Task("live-ti-controls", TI + "/dynamic_controls", "Remove the checkbox using the button and report the message shown.",
         _has("it's gone"), ("live", "dynamic")),
    Task("live-ti-enable", TI + "/dynamic_controls", "Enable the text field, type 'lean' into it, and report the message shown "
         "after enabling.", _has("it's enabled"), ("live", "dynamic")),
    Task("live-ti-shadow", TI + "/shadowdom", "What does the second line of text on this page say?",
         _has("different text"), ("live", "read")),
    Task("live-ti-slider", TI + "/horizontal_slider", "Set the slider to 4 and report the value the page displays.",
         _has("4"), ("live", "widget")),
    Task("live-ti-keys", TI + "/key_presses", "Press the Tab key on this page and report the result text.",
         _has("tab"), ("live", "widget")),
    Task("live-ti-status", TI + "/status_codes", "Open the 404 status code page and report what the page says about it.",
         _has("404"), ("live", "navigate")),
    Task("live-todomvc", "https://todomvc.com/examples/react/dist/", "Add three todos ('a', 'b', 'c'), mark 'b' as "
         "completed, and report how many items are left.", _has("2"), ("live", "widget")),
    Task("live-wiki-search", "https://en.wikipedia.org/wiki/Main_Page", "Use the site's search to find the article on "
         "Ada Lovelace and report the year she was born.", _year(1815), ("live", "form")),
    Task("live-hn-links", "https://news.ycombinator.com/", "List the titles and full URLs of the first three stories. "
         "Every URL must start with http.", _has("http"), ("live", "read")),
]

# Second hardening batch (2026-11-22): sites built as automation challenges. Client-side only; nothing is sent
# to a real account.
UTP = "http://uitestingplayground.com"
DQ = "https://demoqa.com"
LIVE_TASKS += [
    Task("live-utp-classattr", UTP + "/classattr", "Click the blue (primary) button and report the text of the alert it shows.",
         _has("primary button pressed"), ("live2", "dialog")),
    Task("live-utp-loaddelay", UTP + "/", "Open the 'Load Delay' page, wait for its button, and report the button's label.",
         _has("appearing after delay"), ("live2", "dynamic")),
    Task("live-utp-ajax", UTP + "/ajax", "Click the button that triggers the AJAX request and report the text that appears "
         "when the data arrives (it can take about 15 seconds).", _has("data loaded with ajax get request"), ("live2", "dynamic")),
    Task("live-utp-clientdelay", UTP + "/clientdelay", "Click the button that starts the client-side calculation and report "
         "the text that appears when it finishes (it can take about 15 seconds).", _has("data calculated on the client side"),
         ("live2", "dynamic")),
    Task("live-utp-textinput", UTP + "/textinput", "Type 'Lean Bot' into the text field, click the button, and report the "
         "button's new label.", _has("lean bot"), ("live2", "form")),
    Task("live-utp-verifytext", UTP + "/verifytext", "What does the welcome text on this page say?", _has("welcome username"),
         ("live2", "read")),
    Task("live-utp-mouseover", UTP + "/mouseover", "Click the 'Click me' link twice and report the click count the page shows.",
         _has("2"), ("live2", "widget")),
    Task("live-utp-alerts", UTP + "/alerts", "Click the 'Alert' button and report the alert's text.", _has("working day"),
         ("live2", "dialog")),
    Task("live-dq-textbox", DQ + "/text-box", "Fill Full Name 'Lean Tester' and Email 'lean@example.com', submit, and report "
         "the name shown in the output below the form.", _has("lean tester"), ("live2", "form")),
    Task("live-dq-radio", DQ + "/radio-button", "Select the 'Impressive' option and report the confirmation text.",
         _has("impressive"), ("live2", "widget")),
    Task("live-dq-webtables", DQ + "/webtables", "What is Cierra's salary in the table?", _has("10000"), ("live2", "read")),
    Task("live-dq-select", DQ + "/select-menu", "In the 'Old Style Select Menu', choose 'Purple' and report the selected value.",
         _has("purple"), ("live2", "widget")),
    Task("live-dq-doubleclick", DQ + "/buttons", "Double-click the 'Double Click Me' button and report the message that appears.",
         _has("double click"), ("live2", "widget")),
    Task("live-dq-modal", DQ + "/modal-dialogs", "Open the small modal and report the sentence inside it.",
         _has("small modal"), ("live2", "dialog")),
    Task("live-dq-dynamic", DQ + "/dynamic-properties", "A button appears on this page after a few seconds. Report its label.",
         _has("visible after 5 seconds"), ("live2", "dynamic")),
    Task("live-dq-date", DQ + "/date-picker", "Set the 'Select Date' field to 01/15/2025 and report the value the field shows.",
         _has("01/15/2025"), ("live2", "widget")),
    Task("live-dq-autocomplete", DQ + "/auto-complete", "In the single-color autocomplete field, type 'Re' and pick 'Red' from "
         "the suggestions. Report the value that is selected.", _has("red"), ("live2", "widget")),
    Task("live-dq-slider", DQ + "/slider", "Set the slider to 70 and report the value shown next to it.", _has("70"),
         ("live2", "widget")),
    Task("live-dq-tabs", DQ + "/tabs", "Open the 'Origin' tab and report the first three words of its text.",
         _has("contrary to popular"), ("live2", "widget")),
]
BY_ID = {t.id: t for t in LIVE_TASKS}
