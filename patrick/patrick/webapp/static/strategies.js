/* Laboratoire de stratégies (/strategies) : formulaire d'étude (instruments, période, modèle ou règles libres, pondération, risque, frais,
   robustesse), étude en tâche de fond, résultats (performance, opérations, risque, robustesse) et comparaison des études passées.
   Les textes viennent du bloc JSON `#st-i18n` (clés `st_*`) ; aucun calcul financier dans le navigateur : tout arrive de /api/strategies/*.
   Fonctions pures (description des règles, grille, CSV, description de l'étude) testées sous Node. */
(function (root) {
    "use strict";

    // ------------------------------------------------------------------ fonctions pures
    var OP_SYMBOL = { ">": ">", "<": "<", ">=": "≥", "<=": "≤" };
    var PARAM_ORDER = ["n", "skip", "k"];

    function operandText(op, label) {
        if (op === null || op === undefined) return "?";
        if (typeof op === "number") return String(op);
        if (op.value !== undefined) return String(op.value);
        var name = label ? label("st_ind_" + op.ind) : op.ind;
        var args = PARAM_ORDER.filter(function (k) { return op[k] !== undefined; }).map(function (k) { return op[k]; });
        var out = name + (args.length ? "(" + args.join(", ") + ")" : "");
        if (op.symbol) out += " [" + op.symbol + "]";
        if (op.mult !== undefined && op.mult !== 1) out = op.mult + " × " + out;
        if (op.shift) out += " (t−" + op.shift + ")";
        return out;
    }

    function conditionText(c, label) {
        if (!c) return "";
        if (c.all || c.any) return "(" + groupText(c, label) + ")";
        var left = operandText(c.left, label);
        if (c.op === "between" || c.op === "outside") {
            return left + " " + (label ? label("st_op_" + c.op) : c.op) + " [" + operandText(c.low, label) + " ; " + operandText(c.high, label) + "]";
        }
        var op = OP_SYMBOL[c.op] || (label ? label("st_op_" + c.op) : c.op);
        return left + " " + op + " " + operandText(c.right, label);
    }

    function groupText(g, label) {
        if (!g) return "";
        var all = (g.all || []).map(function (c) { return conditionText(c, label); });
        var any = (g.any || []).map(function (c) { return conditionText(c, label); });
        var andWord = label ? " " + label("st_and") + " " : " ET ", orWord = label ? " " + label("st_or") + " " : " OU ";
        var parts = [];
        if (all.length) parts.push(all.join(andWord));
        if (any.length) parts.push(any.length > 1 && all.length ? "(" + any.join(orWord) + ")" : any.join(orWord));
        return parts.join(andWord);
    }

    // Grille de sensibilité : lignes = valeurs du 2e paramètre (ou une seule ligne), colonnes = valeurs du 1er.
    function gridMatrix(grid, metric) {
        if (!grid || !grid.axes || !grid.axes.length) return null;
        var ax = grid.axes[0], ay = grid.axes[1] || null;
        var rows = (ay ? ay.values : [null]).map(function (yv) {
            return ax.values.map(function (xv) {
                var cell = grid.cells.filter(function (c) { return c.params[ax.param] === xv && (!ay || c.params[ay.param] === yv); })[0];
                return cell && cell[metric] !== undefined ? cell[metric] : null;
            });
        });
        var flat = [];
        rows.forEach(function (r) { r.forEach(function (v) { if (v !== null && isFinite(v)) flat.push(v); }); });
        return { x: ax, y: ay, rows: rows, min: flat.length ? Math.min.apply(null, flat) : 0, max: flat.length ? Math.max.apply(null, flat) : 0 };
    }

    // Intensité signée (−1..1) d'une valeur pour colorer une case : rapportée au plus grand écart à zéro.
    function signedIntensity(v, lo, hi) {
        if (v === null || v === undefined || !isFinite(v)) return 0;
        var m = Math.max(Math.abs(lo || 0), Math.abs(hi || 0));
        return m ? Math.max(-1, Math.min(1, v / m)) : 0;
    }

    function csvCell(v) {
        if (v === null || v === undefined) return "";
        var s = String(v);
        return /[";\n]/.test(s) ? "\"" + s.replace(/"/g, "\"\"") + "\"" : s;
    }
    function toCsv(rows) { return rows.map(function (r) { return r.map(csvCell).join(";"); }).join("\r\n"); }

    function tradesCsv(trades) {
        return toCsv([["symbol", "side", "entry", "entry_price", "exit", "exit_price", "days", "return", "pnl", "costs", "reason"]].concat(trades.map(function (x) {
            return [x.symbol, x.side, x.entry, x.entry_price, x.exit || "", x.exit_price, x.days, x.return, x.pnl, x.costs, x.reason];
        })));
    }

    function parseSymbols(text) {
        var out = [];
        String(text || "").split(/[\s,;]+/).forEach(function (tok) {
            var s = tok.trim().toUpperCase();
            if (s && /^[A-Z0-9^][A-Z0-9.=^_\-\/]{0,40}$/.test(s) && out.indexOf(s) < 0) out.push(s);
        });
        return out;
    }

    // Description JSON envoyée au serveur à partir de l'état du formulaire (valeurs vides omises, pourcentages laissés en %).
    function specOf(f) {
        var spec = { name: f.name, symbols: f.symbols.slice(), benchmark: f.benchmark, start: f.start, end: f.end, oos_start: f.oos || null,
                     capital: f.capital, template: f.template, params: f.params, costs: f.costs, execution: f.execution, risk: f.risk,
                     robustness: { random: f.robustness.random, bootstrap: f.robustness.bootstrap, grid: null }, allow_yahoo: f.allow_yahoo };
        if (f.template === "fixed_mix") spec.weights = f.weights;
        if (f.events) spec.events = f.events;
        if (f.rules) spec.rules = f.rules;
        var sz = {};
        Object.keys(f.sizing || {}).forEach(function (k) { if (f.sizing[k] !== "" && f.sizing[k] !== null && f.sizing[k] !== undefined) sz[k] = f.sizing[k]; });
        if (Object.keys(sz).length) spec.sizing = sz;
        if (f.decision) spec.decision = f.decision;
        if (f.rebalance) spec.rebalance = f.rebalance;
        var g = f.robustness.grid;
        if (g && g.x && g.x.param) {
            spec.robustness.grid = { x: g.x };
            if (g.y && g.y.param && g.y.param !== g.x.param) spec.robustness.grid.y = g.y;
        }
        return spec;
    }

    function verdictTone(state) { return state === "robust" ? "ok" : (state === "fragile" ? "warning" : "error"); }
    function checkTone(ok) { return ok === true ? "ok" : (ok === false ? "error" : "disabled"); }

    // Courbe ramenée à 100 au premier point connu (comparaison de plusieurs études).
    function rebase(values) {
        var first = null;
        return values.map(function (v) {
            if (v === null || v === undefined || !isFinite(v)) return null;
            if (first === null) first = v;
            return first ? 100 * v / first : null;
        });
    }

    var api = { operandText: operandText, conditionText: conditionText, groupText: groupText, gridMatrix: gridMatrix, signedIntensity: signedIntensity,
                toCsv: toCsv, tradesCsv: tradesCsv, parseSymbols: parseSymbols, specOf: specOf, verdictTone: verdictTone, checkTone: checkTone, rebase: rebase };
    if (typeof module !== "undefined" && module.exports) { module.exports = api; return; }

    // ------------------------------------------------------------------ page
    var doc = root.document;
    var appEl = doc.getElementById("st-app");
    if (!appEl) return;
    var I18N = {};
    try { I18N = JSON.parse(doc.getElementById("st-i18n").textContent); } catch (e) { I18N = {}; }
    var lang = doc.documentElement.lang || "fr";
    var STORE_KEY = "patrick.strategies.form.v2";
    var PALETTE = ["--brand", "--pos", "--warn", "--neg", "--info", "--text-2", "--ra-c1", "--ra-c5"];
    var BASKETS = {
        indices: ["^GSPC", "^NDX", "^STOXX50E", "^FCHI", "^GDAXI", "^N225"],
        etf: ["SPY", "TLT", "GLD", "IEF", "VNQ", "DBC"],
        sectors: ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB"],
        crypto: ["BTC-USD", "ETH-USD"],
        fx: ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X"],
        cac: ["MC.PA", "OR.PA", "TTE.PA", "SAN.PA", "AIR.PA", "BNP.PA", "SU.PA", "AI.PA"]
    };

    function t(key, params) {
        var s = I18N[key] || key;
        if (params) Object.keys(params).forEach(function (k) { s = s.split("{" + k + "}").join(params[k]); });
        return s;
    }
    function fmt(x, d) { return x === null || x === undefined || !isFinite(x) ? "—" : Number(x).toLocaleString(lang, { minimumFractionDigits: d, maximumFractionDigits: d }); }
    function pct(x, d) { return x === null || x === undefined || !isFinite(x) ? "—" : fmt(x * 100, d === undefined ? 1 : d) + " %"; }
    function money(x) { return x === null || x === undefined || !isFinite(x) ? "—" : Math.round(x).toLocaleString(lang) + " €"; }
    function num(x, d) { return fmt(x, d === undefined ? 2 : d); }

    function h(tag, attrs, children) {
        var el = doc.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) {
            var v = attrs[k];
            if (v === null || v === undefined || v === false) return;
            if (k === "text") el.textContent = v;
            else if (k.slice(0, 2) === "on" && typeof v === "function") el.addEventListener(k.slice(2), v);
            else if (k === "checked" || k === "disabled" || k === "selected" || k === "hidden") el[k] = !!v;
            else if (k === "value") el.value = v;
            else el.setAttribute(k, v === true ? "" : v);
        });
        (children || []).forEach(function (c) { if (c !== null && c !== undefined && c !== false) el.appendChild(typeof c === "string" ? doc.createTextNode(c) : c); });
        return el;
    }
    function hint(text) { return h("p", { class: "hint", "data-keep": "", text: text }); }
    function clear(el) { el.textContent = ""; return el; }
    function badge(text, tone) { return h("span", { class: "status-badge status-" + tone, text: text }); }

    function call(method, url, body, isForm) {
        var opt = { method: method, headers: { Accept: "application/json" } };
        if (body !== undefined) {
            if (isForm) opt.body = body;
            else { opt.body = JSON.stringify(body); opt.headers["Content-Type"] = "application/json"; }
        }
        return root.fetch(url, opt).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (j) {
                if (!r.ok) throw new Error(j.detail ? (typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail)) : ("HTTP " + r.status));
                return j;
            });
        });
    }

    function paint(host, opts) {
        root.setTimeout(function () { if (root.PatrickPlot && host.isConnected) root.PatrickPlot.create(host, opts); }, 0);
        return host;
    }
    function chartBox(label, cls) { return h("div", { class: "st-chart " + (cls || ""), role: "img", "aria-label": label }); }

    function today() { return new Date().toISOString().slice(0, 10); }
    function yearsAgo(n) { var d = new Date(); d.setFullYear(d.getFullYear() - n); return d.toISOString().slice(0, 10); }

    function defaultForm() {
        return { name: t("st_default_name"), symbols: ["SPY"], benchmark: "", start: yearsAgo(20), end: today(), oos: yearsAgo(5), capital: 10000,
                 template: "sma_cross", params: {}, weights: {}, events: { source: "earnings", dates: "" }, risk: {}, sizing: {}, decision: "", rebalance: "",
                 costs: { commission: 0.10, min_fee: 1, fixed: 0, slippage: 5, borrow: 1, cash_rate: 2, financing_spread: 1 },
                 execution: { lag: 1, at: "close" }, robustness: { random: true, bootstrap: true, grid: { x: { param: "", min: "", max: "", steps: 6 }, y: { param: "", min: "", max: "", steps: 5 } } },
                 allow_yahoo: true, rules: null };
    }

    var state = { catalog: null, assets: [], form: defaultForm(), pricesFile: null, eventsFile: null, inspect: null, runs: [], result: null, runId: null,
                  tab: "perf", compare: [], timer: null, logScale: false, tradeFilter: "", tradeSort: "entry", notice: "", rulesOpen: false };
    try {
        var saved = JSON.parse(root.localStorage.getItem(STORE_KEY) || "null");
        if (saved && saved.symbols) state.form = Object.assign(defaultForm(), saved);
    } catch (e) { /* stockage indisponible */ }
    function remember() { try { root.localStorage.setItem(STORE_KEY, JSON.stringify(state.form)); } catch (e) { /* stockage indisponible */ } }

    var els = { form: doc.getElementById("st-form-body"), result: doc.getElementById("st-result"), resultBody: doc.getElementById("st-result-body"),
                history: doc.getElementById("st-history-body") };

    function tplMeta(key) { return (state.catalog.templates.filter(function (x) { return x.key === key; })[0]) || null; }
    function paramValue(name) {
        var meta = tplMeta(state.form.template);
        var p = meta && meta.params[name];
        var v = state.form.params[name];
        return v === undefined ? (p ? p.default : "") : v;
    }

    // ------------------------------------------------------------------ formulaire : instruments et période
    function universeBlock() {
        var f = state.form;
        var chips = h("div", { class: "st-chips", role: "list" }, f.symbols.map(function (s) {
            var name = (state.assets.filter(function (a) { return a.s === s; })[0] || {}).n;
            return h("span", { class: "st-chip", role: "listitem", title: name || s }, [h("span", { text: s }), name && name !== s ? h("span", { class: "hint", text: " " + name }) : null,
                h("button", { type: "button", class: "st-chip-x", "aria-label": t("st_remove") + " " + s, text: "×", onclick: function () { f.symbols = f.symbols.filter(function (x) { return x !== s; }); remember(); renderForm(); } })]);
        }));
        var list = h("datalist", { id: "st-assets" }, state.assets.slice(0, 3000).map(function (a) { return h("option", { value: a.s, text: a.n + " · " + a.g }); }));
        var input = h("input", { type: "text", class: "st-input st-grow", list: "st-assets", placeholder: t("st_add_ph"), "aria-label": t("st_add_ph"),
            onkeydown: function (e) { if (e.key === "Enter") { e.preventDefault(); add(); } } });
        function add() {
            parseSymbols(input.value).forEach(function (s) { if (f.symbols.indexOf(s) < 0) f.symbols.push(s); });
            input.value = ""; remember(); renderForm();
        }
        var baskets = h("div", { class: "st-baskets" }, [h("span", { class: "hint", text: t("st_baskets") })].concat(Object.keys(BASKETS).map(function (k) {
            return h("button", { type: "button", class: "btn-secondary st-small", text: t("st_basket_" + k), onclick: function () {
                BASKETS[k].forEach(function (s) { if (f.symbols.indexOf(s) < 0) f.symbols.push(s); }); remember(); renderForm();
            } });
        })).concat([f.symbols.length ? h("button", { type: "button", class: "btn-secondary st-small", text: t("st_clear"), onclick: function () { f.symbols = []; remember(); renderForm(); } }) : null]));
        var file = h("input", { type: "file", accept: ".csv,.txt,.tsv,.xlsx,.xlsm,.xls,.ods", "aria-label": t("st_prices_file"), onchange: function (e) {
            var fl = e.target.files[0];
            state.pricesFile = fl || null; state.inspect = null;
            if (!fl) { renderForm(); return; }
            var body = new FormData(); body.append("prices_file", fl, fl.name);
            fileStatus.textContent = t("st_reading");
            call("POST", "/api/strategies/inspect", body, true).then(function (res) { state.inspect = res; renderForm(); })
                .catch(function (err) { state.inspect = { error: err.message }; renderForm(); });
        } });
        var fileStatus = h("span", { class: "hint" });
        var ins = state.inspect;
        var inspectBox = null;
        if (ins && ins.error) inspectBox = h("p", { class: "st-error", text: ins.error });
        else if (ins) {
            inspectBox = h("div", { class: "st-inspect" }, [
                h("p", { class: "hint", text: t("st_inspect_line", { n: ins.count }) + (ins.notes.length ? " · " + ins.notes.join(" · ") : "") }),
                h("div", { class: "st-chips" }, ins.symbols.slice(0, 40).map(function (x) { return h("span", { class: "st-chip st-chip-file", text: x.symbol + " (" + x.first.slice(0, 4) + "–" + x.last.slice(0, 4) + ")" }); })),
                h("button", { type: "button", class: "btn-secondary st-small", text: t("st_add_file_symbols", { n: Math.min(ins.count, 60) }), onclick: function () {
                    ins.symbols.slice(0, 60).forEach(function (x) { if (f.symbols.indexOf(x.symbol) < 0) f.symbols.push(x.symbol); }); remember(); renderForm();
                } })]);
        }
        var yahoo = h("label", { class: "st-check" }, [h("input", { type: "checkbox", checked: f.allow_yahoo, onchange: function (e) { f.allow_yahoo = e.target.checked; remember(); } }), t("st_allow_yahoo")]);
        function dateInput(key, label) {
            return h("label", { class: "st-field" }, [h("span", { text: label }), h("input", { type: "date", class: "st-input", value: f[key] || "", onchange: function (e) { f[key] = e.target.value; remember(); } })]);
        }
        var quick = h("div", { class: "st-quick" }, [5, 10, 20, 30].map(function (n) {
            return h("button", { type: "button", class: "btn-secondary st-small", text: t("st_years", { n: n }), onclick: function () {
                f.start = yearsAgo(n); f.end = today(); f.oos = yearsAgo(Math.max(1, Math.round(n * 0.3))); remember(); renderForm();
            } });
        }));
        var bench = h("select", { class: "st-input", "aria-label": t("st_benchmark"), onchange: function (e) { f.benchmark = e.target.value === "__custom__" ? (benchInput.value || "") : e.target.value; remember(); renderForm(); } },
            [["", t("st_bench_auto")], ["__EQUAL__", t("st_bench_equal")], ["__CASH__", t("st_bench_cash")], ["__custom__", t("st_bench_symbol")]].map(function (o) {
                var custom = f.benchmark && ["", "__EQUAL__", "__CASH__"].indexOf(f.benchmark) < 0;
                return h("option", { value: o[0], selected: custom ? o[0] === "__custom__" : f.benchmark === o[0], text: o[1] });
            }));
        var benchInput = h("input", { type: "text", class: "st-input st-narrow", list: "st-assets", placeholder: "^GSPC", value: ["", "__EQUAL__", "__CASH__"].indexOf(f.benchmark) < 0 ? f.benchmark : "",
            "aria-label": t("st_bench_symbol"), onchange: function (e) { f.benchmark = e.target.value.trim().toUpperCase(); remember(); } });
        return h("fieldset", { class: "st-block" }, [h("legend", { text: t("st_universe_h") }), chips, list,
            h("div", { class: "st-row" }, [input, h("button", { type: "button", class: "btn-secondary", text: t("st_add"), onclick: add })]), baskets,
            h("div", { class: "st-row st-file" }, [h("span", { class: "st-label", text: t("st_prices_file") }), file, fileStatus, yahoo]), hint(t("st_prices_hint")), inspectBox,
            h("div", { class: "st-row st-wrap" }, [dateInput("start", t("st_start")), dateInput("end", t("st_end")), dateInput("oos", t("st_oos")), quick]),
            hint(t("st_oos_hint")),
            h("div", { class: "st-row st-wrap" }, [
                h("label", { class: "st-field" }, [h("span", { text: t("st_capital") }), h("input", { type: "number", class: "st-input st-narrow", min: "100", step: "1000", value: String(f.capital), onchange: function (e) { f.capital = parseFloat(e.target.value) || 10000; remember(); } })]),
                h("label", { class: "st-field" }, [h("span", { text: t("st_benchmark") }), bench]),
                bench.value === "__custom__" ? h("label", { class: "st-field" }, [h("span", { text: t("st_bench_symbol") }), benchInput]) : null])]);
    }

    // ------------------------------------------------------------------ formulaire : modèle et paramètres
    function galleryBlock() {
        var f = state.form;
        var fams = state.catalog.families;
        var gallery = h("div", { class: "st-gallery", role: "radiogroup", "aria-label": t("st_template_h") }, fams.map(function (fam) {
            var items = state.catalog.templates.filter(function (x) { return x.family === fam; });
            return h("div", { class: "st-family" }, [h("h4", { class: "st-family-h", text: t("st_fam_" + fam) })].concat(items.map(function (x) {
                return h("button", { type: "button", role: "radio", class: "st-tpl" + (x.key === f.template ? " is-on" : ""), "aria-checked": x.key === f.template ? "true" : "false",
                    onclick: function () { f.template = x.key; f.params = {}; f.rules = null; f.robustness.grid = defaultForm().robustness.grid; state.rulesOpen = x.key === "custom"; remember(); renderForm(); } },
                    [h("strong", { text: t("st_tpl_" + x.key) }), h("span", { class: "hint", text: t("st_tpl_" + x.key + "_d") })]);
            })));
        }));
        var meta = tplMeta(f.template);
        var fields = Object.keys(meta.params).map(function (name) {
            var p = meta.params[name], v = paramValue(name);
            var label = t("st_p_" + name);
            var input;
            if (p.type === "select") {
                input = h("select", { class: "st-input", onchange: function (e) { f.params[name] = e.target.value; f.rules = null; remember(); renderForm(); } },
                    p.options.map(function (o) { return h("option", { value: o, selected: o === v, text: t("st_opt_" + o) }); }));
            } else if (p.type === "bool") {
                input = h("input", { type: "checkbox", checked: !!v, onchange: function (e) { f.params[name] = e.target.checked; f.rules = null; remember(); } });
            } else if (p.type === "symbol") {
                input = h("input", { type: "text", class: "st-input st-narrow", list: "st-assets", value: v, onchange: function (e) { f.params[name] = e.target.value.trim().toUpperCase(); f.rules = null; remember(); } });
            } else {
                input = h("input", { type: "number", class: "st-input st-narrow", min: p.min, max: p.max, step: p.step, value: String(v),
                    onchange: function (e) { var x = parseFloat(e.target.value); if (isFinite(x)) f.params[name] = x; f.rules = null; remember(); } });
            }
            return h("label", { class: "st-field" }, [h("span", { text: label }), input]);
        });
        var weights = null;
        if (meta.weights) {
            weights = h("div", { class: "st-row st-wrap" }, [h("span", { class: "st-label", text: t("st_weights") })].concat(f.symbols.map(function (s) {
                return h("label", { class: "st-field" }, [h("span", { text: s }), h("input", { type: "number", class: "st-input st-narrow", min: "0", step: "5", value: String(f.weights[s] !== undefined ? f.weights[s] : Math.round(100 / Math.max(f.symbols.length, 1))),
                    onchange: function (e) { f.weights[s] = parseFloat(e.target.value) || 0; remember(); } })]);
            })));
        }
        var eventsBox = null;
        if (meta.events) {
            var src = f.events.source;
            eventsBox = h("div", { class: "st-events" }, [
                h("div", { class: "st-row st-wrap" }, [h("span", { class: "st-label", text: t("st_events_src") })].concat(["earnings", "file", "dates"].map(function (k) {
                    return h("label", { class: "st-check" }, [h("input", { type: "radio", name: "st-ev", checked: src === k, onchange: function () { f.events.source = k; remember(); renderForm(); } }), t("st_ev_" + k)]);
                }))),
                src === "file" ? h("input", { type: "file", accept: ".csv,.txt,.xlsx,.xls,.ods", "aria-label": t("st_ev_file"), onchange: function (e) { state.eventsFile = e.target.files[0] || null; } }) : null,
                src === "dates" ? h("textarea", { class: "st-input st-area", rows: "3", placeholder: "2024-01-31\n2024-03-20", "aria-label": t("st_ev_dates"), onchange: function (e) { f.events.dates = e.target.value; remember(); } }, [f.events.dates || ""]) : null,
                hint(t("st_ev_hint_" + src))]);
        }
        var pairHint = meta.pair ? hint(t("st_pair_hint")) : null;
        return h("fieldset", { class: "st-block" }, [h("legend", { text: t("st_template_h") }), gallery,
            h("div", { class: "st-tpl-detail" }, [h("h4", { text: t("st_tpl_" + f.template) }), hint(t("st_tpl_" + f.template + "_long")),
                fields.length ? h("div", { class: "st-row st-wrap" }, fields) : null, weights, eventsBox, pairHint]),
            rulesBlock()]);
    }

    // ------------------------------------------------------------------ constructeur de règles
    var RULE_KEYS = ["long_entry", "long_exit", "short_entry", "short_exit"];

    function operandEditor(op, onChange, allowValue) {
        op = op || { value: 0 };
        var kinds = (allowValue ? ["value"] : []).concat(Object.keys(state.catalog.indicators));
        var current = op.value !== undefined ? "value" : op.ind;
        var sel = h("select", { class: "st-input st-op-kind", "aria-label": t("st_operand"), onchange: function (e) {
            var k = e.target.value;
            if (k === "value") onChange({ value: 0 });
            else onChange(Object.assign({ ind: k }, state.catalog.indicators[k].params));
        } }, kinds.map(function (k) { return h("option", { value: k, selected: k === current, text: k === "value" ? t("st_value") : t("st_ind_" + k) }); }));
        var parts = [sel];
        if (current === "value") {
            parts.push(h("input", { type: "number", class: "st-input st-tiny", step: "any", value: String(op.value), "aria-label": t("st_value"), onchange: function (e) { onChange({ value: parseFloat(e.target.value) || 0 }); } }));
        } else {
            Object.keys(state.catalog.indicators[current].params).forEach(function (pn) {
                parts.push(h("input", { type: "number", class: "st-input st-tiny", step: "any", title: t("st_p_" + pn), "aria-label": t("st_p_" + pn), value: String(op[pn] !== undefined ? op[pn] : state.catalog.indicators[current].params[pn]),
                    onchange: function (e) { var c = Object.assign({}, op); c[pn] = parseFloat(e.target.value); onChange(c); } }));
            });
            parts.push(h("input", { type: "text", class: "st-input st-tiny st-sym", list: "st-assets", placeholder: t("st_on_symbol"), title: t("st_on_symbol_hint"), value: op.symbol || "",
                "aria-label": t("st_on_symbol"), onchange: function (e) { var c = Object.assign({}, op); var v = e.target.value.trim().toUpperCase(); if (v) c.symbol = v; else delete c.symbol; onChange(c); } }));
        }
        return h("span", { class: "st-operand" }, parts);
    }

    function conditionEditor(c, onChange, onRemove) {
        var op = h("select", { class: "st-input st-op", "aria-label": t("st_operator"), onchange: function (e) {
            var n = Object.assign({}, c, { op: e.target.value });
            if (n.op === "between" || n.op === "outside") { delete n.right; n.low = n.low || { value: 0 }; n.high = n.high || { value: 1 }; }
            else { delete n.low; delete n.high; n.right = n.right || { value: 0 }; }
            onChange(n);
        } }, state.catalog.ops.map(function (o) { return h("option", { value: o, selected: o === c.op, text: OP_SYMBOL[o] || t("st_op_" + o) }); }));
        var row = [operandEditor(c.left, function (v) { onChange(Object.assign({}, c, { left: v })); }, false), op];
        if (c.op === "between" || c.op === "outside") {
            row.push(operandEditor(c.low, function (v) { onChange(Object.assign({}, c, { low: v })); }, true));
            row.push(h("span", { class: "hint", text: t("st_and") }));
            row.push(operandEditor(c.high, function (v) { onChange(Object.assign({}, c, { high: v })); }, true));
        } else {
            row.push(operandEditor(c.right, function (v) { onChange(Object.assign({}, c, { right: v })); }, true));
        }
        row.push(h("button", { type: "button", class: "btn-secondary st-small", "aria-label": t("st_remove_cond"), text: "×", onclick: onRemove }));
        return h("div", { class: "st-cond" }, row);
    }

    function groupEditor(key) {
        var rulesObj = state.form.rules;
        var g = rulesObj[key] || null;
        var mode = g && g.any && g.any.length && !(g.all && g.all.length) ? "any" : "all";
        var list = g ? (g[mode] || []) : [];
        function save(newList, newMode) {
            var m = newMode || mode;
            rulesObj[key] = newList.length ? (function () { var o = {}; o[m] = newList; return o; })() : null;
            remember(); renderForm();
        }
        var modeSel = h("select", { class: "st-input st-narrow", "aria-label": t("st_group_mode"), onchange: function (e) { save(list, e.target.value); } },
            [["all", t("st_mode_all")], ["any", t("st_mode_any")]].map(function (o) { return h("option", { value: o[0], selected: o[0] === mode, text: o[1] }); }));
        var nested = g && g.all && g.any && g.all.length && g.any.length;
        return h("div", { class: "st-group" }, [
            h("div", { class: "st-group-h" }, [h("strong", { text: t("st_rule_" + key) }), list.length > 1 ? modeSel : null,
                h("span", { class: "hint", text: g ? groupText(g, t) : t("st_rule_none_" + key) })]),
            nested ? hint(t("st_nested_hint")) : null,
            h("div", {}, nested ? [] : list.map(function (c, i) {
                return conditionEditor(c, function (nc) { var copy = list.slice(); copy[i] = nc; save(copy); }, function () { var copy = list.slice(); copy.splice(i, 1); save(copy); });
            })),
            nested ? null : h("button", { type: "button", class: "btn-secondary st-small", text: t("st_add_cond"), onclick: function () {
                save(list.concat([{ left: { ind: "price" }, op: ">", right: { ind: "sma", n: 200 } }]));
            } })]);
    }

    function selectionEditor() {
        var r = state.form.rules;
        var s = r.selection;
        var on = h("label", { class: "st-check" }, [h("input", { type: "checkbox", checked: !!s, onchange: function (e) {
            r.selection = e.target.checked ? { rank_by: { ind: "ret", n: 126 }, order: "desc", top: Math.min(3, state.form.symbols.length), bottom: 0 } : null; remember(); renderForm();
        } }), t("st_selection_on")]);
        if (!s) return h("div", { class: "st-group" }, [on, hint(t("st_selection_hint"))]);
        function upd(k, v) { r.selection = Object.assign({}, s); r.selection[k] = v; remember(); renderForm(); }
        return h("div", { class: "st-group" }, [on, h("div", { class: "st-row st-wrap" }, [
            h("span", { class: "st-label", text: t("st_rank_by") }), operandEditor(s.rank_by, function (v) { upd("rank_by", v); }, false),
            h("select", { class: "st-input st-narrow", "aria-label": t("st_order"), onchange: function (e) { upd("order", e.target.value); } },
                [["desc", t("st_order_desc")], ["asc", t("st_order_asc")]].map(function (o) { return h("option", { value: o[0], selected: s.order === o[0], text: o[1] }); })),
            h("label", { class: "st-field" }, [h("span", { text: t("st_top") }), h("input", { type: "number", class: "st-input st-tiny", min: "0", max: "60", value: String(s.top || 0), onchange: function (e) { upd("top", parseInt(e.target.value, 10) || 0); } })]),
            h("label", { class: "st-field" }, [h("span", { text: t("st_bottom") }), h("input", { type: "number", class: "st-input st-tiny", min: "0", max: "60", value: String(s.bottom || 0), onchange: function (e) { upd("bottom", parseInt(e.target.value, 10) || 0); } })])])]);
    }

    function rulesBlock() {
        var f = state.form;
        var summary = h("summary", {}, [h("strong", { text: t("st_rules_h") }), " ", f.rules ? badge(t("st_rules_custom"), "warning") : h("span", { class: "hint", text: t("st_rules_from_tpl") })]);
        var body = h("div", { class: "st-rules" });
        var box = h("details", { class: "st-rules-box", open: state.rulesOpen || !!f.rules, ontoggle: function (e) { state.rulesOpen = e.target.open; } }, [summary, body]);
        if (!f.rules) {
            body.appendChild(hint(t("st_rules_intro")));
            var preview = h("div", { class: "st-rules-preview" }, [hint(t("st_reading"))]);
            body.appendChild(preview);
            call("POST", "/api/strategies/compile", { template: f.template, params: f.params }).then(function (built) {
                clear(preview);
                RULE_KEYS.concat(["selection"]).forEach(function (k) {
                    if (k === "selection") { if (built.selection) preview.appendChild(h("p", {}, [h("strong", { text: t("st_selection_on") + " : " }), t("st_sel_line", { top: built.selection.top, bottom: built.selection.bottom || 0, by: operandText(built.selection.rank_by, t) })])); return; }
                    if (built[k]) preview.appendChild(h("p", {}, [h("strong", { text: t("st_rule_" + k) + " : " }), groupText(built[k], t)]));
                });
                if (!preview.childNodes.length) preview.appendChild(hint(t("st_rules_always")));
                preview.appendChild(h("button", { type: "button", class: "btn-secondary st-small", text: t("st_rules_edit"), onclick: function () {
                    f.rules = { long_entry: built.long_entry || null, long_exit: built.long_exit || null, short_entry: built.short_entry || null, short_exit: built.short_exit || null, selection: built.selection || null };
                    state.rulesOpen = true; remember(); renderForm();
                } }));
            }).catch(function (e) { clear(preview).appendChild(h("p", { class: "st-error", text: e.message })); });
            return box;
        }
        body.appendChild(hint(t("st_rules_custom_hint")));
        RULE_KEYS.forEach(function (k) { body.appendChild(groupEditor(k)); });
        body.appendChild(selectionEditor());
        body.appendChild(h("button", { type: "button", class: "btn-secondary st-small", text: t("st_rules_reset"), onclick: function () { f.rules = null; remember(); renderForm(); } }));
        return box;
    }

    // ------------------------------------------------------------------ formulaire : pondération, risque, frais, robustesse
    function numberField(obj, key, label, attrs, after) {
        var a = Object.assign({ type: "number", class: "st-input st-narrow", value: obj[key] === undefined || obj[key] === null ? "" : String(obj[key]),
            onchange: function (e) { var v = e.target.value === "" ? "" : parseFloat(e.target.value); obj[key] = v; remember(); if (after) after(); } }, attrs || {});
        return h("label", { class: "st-field" }, [h("span", { text: label }), h("input", a)]);
    }

    function sizingBlock() {
        var f = state.form, sz = f.sizing;
        function sel(key, options, label, value, target) {
            return h("label", { class: "st-field" }, [h("span", { text: label }), h("select", { class: "st-input", onchange: function (e) { (target || sz)[key] = e.target.value; remember(); } },
                options.map(function (o) { return h("option", { value: o, selected: o === value, text: o ? t("st_opt_" + o) : t("st_from_tpl") }); }))]);
        }
        return h("fieldset", { class: "st-block" }, [h("legend", { text: t("st_sizing_h") }),
            h("div", { class: "st-row st-wrap" }, [
                sel("method", [""].concat(state.catalog.sizing), t("st_sizing_method"), sz.method || ""),
                sel("allocation", ["", "sleeves", "active"], t("st_allocation"), sz.allocation || ""),
                numberField(sz, "n", t("st_vol_window"), { min: "5", max: "400", step: "5", placeholder: "60" }),
                numberField(sz, "target", t("st_line_target"), { min: "0.01", max: "1", step: "0.01", placeholder: "0.10" }),
                numberField(sz, "max_weight", t("st_max_weight"), { min: "0.01", max: "3", step: "0.05", placeholder: "1" }),
                numberField(sz, "leverage", t("st_leverage"), { min: "0.1", max: "5", step: "0.1", placeholder: "1" })]),
            hint(t("st_sizing_hint")),
            h("div", { class: "st-row st-wrap" }, [
                sel("decision", ["", "daily", "weekly", "monthly", "quarterly"], t("st_decision"), f.decision || "", f),
                sel("rebalance", ["", "never", "daily", "weekly", "monthly", "quarterly", "annual"], t("st_rebalance"), f.rebalance || "", f)]),
            h("div", { class: "st-row st-wrap" }, [
                numberField(f.risk, "stop_loss", t("st_stop_loss"), { min: "0", max: "95", step: "0.5", placeholder: "—" }),
                numberField(f.risk, "take_profit", t("st_take_profit"), { min: "0", max: "1000", step: "1", placeholder: "—" }),
                numberField(f.risk, "trailing", t("st_trailing"), { min: "0", max: "95", step: "0.5", placeholder: "—" }),
                numberField(f.risk, "max_days", t("st_max_days"), { min: "0", max: "2520", step: "1", placeholder: "—" })]),
            hint(t("st_risk_hint"))]);
    }

    function costsBlock() {
        var f = state.form, c = f.costs;
        var presets = h("div", { class: "st-baskets" }, [h("span", { class: "hint", text: t("st_cost_presets") })].concat(Object.keys(state.catalog.cost_presets).map(function (k) {
            return h("button", { type: "button", class: "btn-secondary st-small", text: t("st_preset_" + k), onclick: function () { Object.assign(c, state.catalog.cost_presets[k]); remember(); renderForm(); } });
        })));
        return h("fieldset", { class: "st-block" }, [h("legend", { text: t("st_costs_h") }), presets,
            h("div", { class: "st-row st-wrap" }, [
                numberField(c, "commission", t("st_commission"), { min: "0", max: "5", step: "0.01" }),
                numberField(c, "min_fee", t("st_min_fee"), { min: "0", max: "100", step: "0.5" }),
                numberField(c, "fixed", t("st_fixed_fee"), { min: "0", max: "100", step: "0.5" }),
                numberField(c, "slippage", t("st_slippage"), { min: "0", max: "500", step: "1" }),
                numberField(c, "borrow", t("st_borrow"), { min: "0", max: "50", step: "0.25" }),
                numberField(c, "cash_rate", t("st_cash_rate"), { min: "-5", max: "20", step: "0.25" }),
                numberField(c, "financing_spread", t("st_fin_spread"), { min: "0", max: "20", step: "0.25" })]),
            h("div", { class: "st-row st-wrap" }, [
                h("label", { class: "st-field" }, [h("span", { text: t("st_exec_at") }), h("select", { class: "st-input", onchange: function (e) { f.execution.at = e.target.value; if (f.execution.at === "open" && f.execution.lag < 1) f.execution.lag = 1; remember(); renderForm(); } },
                    [["close", t("st_exec_close")], ["open", t("st_exec_open")]].map(function (o) { return h("option", { value: o[0], selected: f.execution.at === o[0], text: o[1] }); }))]),
                numberField(f.execution, "lag", t("st_exec_lag"), { min: f.execution.at === "open" ? "1" : "0", max: "5", step: "1" })]),
            hint(t("st_costs_hint"))]);
    }

    function robustnessBlock() {
        var f = state.form, r = f.robustness;
        var meta = tplMeta(f.template);
        var numeric = Object.keys(meta.params).filter(function (k) { return meta.params[k].type === "int" || meta.params[k].type === "float"; });
        function axis(key) {
            var a = r.grid[key];
            var p = meta.params[a.param];
            var pick = h("select", { class: "st-input", "aria-label": t("st_grid_param"), onchange: function (e) {
                a.param = e.target.value; var pm = meta.params[a.param];
                if (pm) { a.min = pm.min; a.max = pm.max; } remember(); renderForm();
            } }, [h("option", { value: "", text: t("st_grid_none") })].concat(numeric.map(function (k) { return h("option", { value: k, selected: k === a.param, text: t("st_p_" + k) }); })));
            return h("div", { class: "st-row st-wrap" }, [h("span", { class: "st-label", text: t("st_grid_" + key) }), pick,
                p ? numberField(a, "min", t("st_min"), { step: p.step }) : null, p ? numberField(a, "max", t("st_max"), { step: p.step }) : null,
                p ? numberField(a, "steps", t("st_steps"), { min: "2", max: "12", step: "1" }) : null]);
        }
        return h("fieldset", { class: "st-block" }, [h("legend", { text: t("st_robust_h") }),
            h("div", { class: "st-row st-wrap" }, [
                h("label", { class: "st-check" }, [h("input", { type: "checkbox", checked: r.random, onchange: function (e) { r.random = e.target.checked; remember(); } }), t("st_rob_random")]),
                h("label", { class: "st-check" }, [h("input", { type: "checkbox", checked: r.bootstrap, onchange: function (e) { r.bootstrap = e.target.checked; remember(); } }), t("st_rob_bootstrap")])]),
            numeric.length && !f.rules ? axis("x") : hint(t("st_grid_unavailable")), numeric.length && !f.rules && r.grid.x.param ? axis("y") : null,
            hint(t("st_robust_hint"))]);
    }

    function runBlock() {
        var bar = h("progress", { class: "st-progress", max: "1", value: "0", hidden: true });
        var status = h("span", { class: "hint", role: "status", "aria-live": "polite" });
        var button = h("button", { type: "button", class: "btn-primary", text: t("st_run"), onclick: function () {
            var f = state.form;
            if (!f.symbols.length) { status.textContent = t("st_need_symbol"); return; }
            var body = new FormData();
            body.append("spec", JSON.stringify(specOf(f)));
            if (state.pricesFile) body.append("prices_file", state.pricesFile, state.pricesFile.name);
            if (state.eventsFile) body.append("events_file", state.eventsFile, state.eventsFile.name);
            button.disabled = true; bar.hidden = false; bar.value = 0; status.textContent = t("st_starting");
            call("POST", "/api/strategies/run", body, true).then(function (job) { poll(job.id, bar, status, button); })
                .catch(function (e) { button.disabled = false; bar.hidden = true; status.textContent = t("st_failed", { e: e.message }); });
        } });
        var name = h("input", { type: "text", class: "st-input st-grow", value: state.form.name, "aria-label": t("st_name"), onchange: function (e) { state.form.name = e.target.value; remember(); } });
        var exportBtn = h("button", { type: "button", class: "btn-secondary st-small", text: t("st_export_spec"), onclick: function () { download("strategie.json", JSON.stringify(specOf(state.form), null, 1), "application/json"); } });
        var importBtn = h("label", { class: "btn-secondary st-small st-file-btn" }, [t("st_import_spec"), h("input", { type: "file", accept: ".json", hidden: true, onchange: function (e) {
            var fl = e.target.files[0]; if (!fl) return;
            fl.text().then(function (txt) { loadSpec(JSON.parse(txt)); }).catch(function () { status.textContent = t("st_bad_spec"); });
        } })]);
        return h("div", { class: "st-run" }, [h("div", { class: "st-row" }, [h("span", { class: "st-label", text: t("st_name") }), name, exportBtn, importBtn]),
            h("div", { class: "st-row" }, [button, bar, status])]);
    }

    function loadSpec(spec) {
        var f = Object.assign(defaultForm(), {
            name: spec.name || t("st_default_name"), symbols: spec.symbols || [], benchmark: spec.benchmark && spec.benchmark !== (spec.symbols || [])[0] ? spec.benchmark : "",
            start: spec.start, end: spec.end, oos: spec.oos_start || "", capital: spec.capital || 10000, template: spec.template || "custom", params: spec.params || {},
            weights: spec.weights || {}, events: spec.events || { source: "earnings", dates: "" }, rules: spec.rules || null, decision: spec.decision || "", rebalance: spec.rebalance || "",
            allow_yahoo: spec.allow_yahoo !== false });
        if (spec.costs) f.costs = Object.assign(f.costs, spec.costs);
        if (spec.execution) f.execution = Object.assign(f.execution, spec.execution);
        if (spec.risk) Object.keys(spec.risk).forEach(function (k) { if (spec.risk[k] !== null) f.risk[k] = spec.risk[k]; });
        if (spec.sizing) f.sizing = Object.assign({}, spec.sizing);
        if (spec.robustness) { f.robustness.random = spec.robustness.random !== false; f.robustness.bootstrap = spec.robustness.bootstrap !== false; if (spec.robustness.grid) f.robustness.grid = Object.assign(f.robustness.grid, spec.robustness.grid); }
        if (!tplMeta(f.template)) f.template = "custom";
        state.form = f; remember(); renderForm();
        root.scrollTo({ top: appEl.offsetTop, behavior: "smooth" });
    }

    function download(name, text, type) {
        var blob = new Blob(["﻿" + text], { type: type || "text/csv;charset=utf-8" });
        var a = h("a", { href: URL.createObjectURL(blob), download: name });
        doc.body.appendChild(a); a.click(); a.remove();
    }

    function poll(jobId, bar, status, button) {
        root.clearTimeout(state.timer);
        call("GET", "/api/strategies/jobs/" + jobId).then(function (job) {
            bar.value = job.fraction || 0;
            status.textContent = (job.message || t("st_running")) + " · " + Math.round(job.elapsed) + " s";
            if (job.status === "running") { state.timer = root.setTimeout(function () { poll(jobId, bar, status, button); }, 800); return; }
            button.disabled = false; bar.hidden = true;
            if (job.status === "error") { status.textContent = t("st_failed", { e: job.error }); return; }
            status.textContent = t("st_done", { s: Math.round(job.elapsed) });
            return loadRun(job.run_id).then(loadRuns);
        }).catch(function (e) { button.disabled = false; bar.hidden = true; status.textContent = t("st_failed", { e: e.message }); });
    }

    function renderForm() {
        if (!state.catalog) return;
        if (!tplMeta(state.form.template)) state.form.template = "sma_cross";
        clear(els.form);
        els.form.appendChild(universeBlock());
        els.form.appendChild(galleryBlock());
        var more = h("details", { class: "st-more" }, [h("summary", { text: t("st_more_h") }), sizingBlock(), costsBlock(), robustnessBlock()]);
        more.open = true;
        els.form.appendChild(more);
        els.form.appendChild(runBlock());
    }

    // ------------------------------------------------------------------ résultats
    function loadRun(id, quiet) {
        if (!id) return Promise.resolve();
        return call("GET", "/api/strategies/runs/" + id).then(function (r) {
            state.result = r; state.runId = id; renderResult();
            if (!quiet) root.scrollTo({ top: els.result.offsetTop - 10, behavior: "smooth" });
        });
    }
    function loadRuns() {
        return call("GET", "/api/strategies/runs").then(function (list) { state.runs = list; renderHistory(); }).catch(function () { /* historique indisponible */ });
    }

    function kpi(label, value, sub, tone) {
        return h("div", { class: "st-kpi" + (tone ? " st-kpi-" + tone : "") }, [h("span", { class: "st-kpi-l", text: label }), h("strong", { class: "st-kpi-v", text: value }), sub ? h("span", { class: "hint", text: sub }) : null]);
    }

    function verdictBlock(r) {
        var v = r.verdict;
        return h("div", { class: "st-verdict st-verdict-" + verdictTone(v.state) }, [
            h("div", { class: "st-verdict-h" }, [badge(t("st_v_" + v.state), verdictTone(v.state)), h("span", { text: t("st_v_" + v.state + "_d") })]),
            h("ul", { class: "st-checks" }, v.checks.map(function (c) {
                return h("li", {}, [badge(c.ok === true ? "✓" : (c.ok === false ? "✗" : "–"), checkTone(c.ok)), " ", t("st_chk_" + c.key)]);
            }))]);
    }

    function kpis(r) {
        var s = r.summary, b = r.benchmark && r.benchmark.metrics, ts = r.trade_stats || {};
        function vs(x, y, f) { return b ? t("st_vs_bench", { v: f(y) }) : ""; }
        return h("div", { class: "st-kpis" }, [
            kpi(t("st_k_pnl"), money(s.pnl), t("st_k_final", { v: money(s.final_equity) }), s.pnl >= 0 ? "pos" : "neg"),
            kpi(t("st_k_cagr"), pct(s.cagr), vs(s.cagr, b && b.cagr, pct)),
            kpi(t("st_k_sharpe"), num(s.sharpe), vs(s.sharpe, b && b.sharpe, num)),
            kpi(t("st_k_mdd"), pct(s.max_dd), vs(s.max_dd, b && b.max_dd, pct), "neg"),
            kpi(t("st_k_vol"), pct(s.vol), vs(s.vol, b && b.vol, pct)),
            kpi(t("st_k_trades"), fmt(ts.count || 0, 0), ts.count ? t("st_k_winrate", { v: pct(ts.win_rate, 0) }) : ""),
            kpi(t("st_k_exposure"), pct(s.exposure, 0), t("st_k_invested", { v: pct(s.time_invested, 0) })),
            kpi(t("st_k_costs"), money(s.costs_total), t("st_k_costs_year", { v: pct(s.costs_annual_share, 2) }))]);
    }

    function tabs(r) {
        var names = ["perf", "trades", "risk", "robust", "compare"];
        return h("div", { class: "st-tabs", role: "tablist" }, names.map(function (n) {
            return h("button", { type: "button", role: "tab", class: "st-tab" + (state.tab === n ? " is-on" : ""), "aria-selected": state.tab === n ? "true" : "false",
                text: t("st_tab_" + n), onclick: function () { state.tab = n; renderResult(); } });
        }));
    }

    function perfTab(r) {
        var se = r.series, xs = se.dates.map(function (d) { return Date.parse(d); });
        var cap = r.spec.capital;
        var useLog = state.logScale;
        function tr(v) { return v === null ? null : (useLog ? Math.log10(v) : v); }
        var series = [{ name: r.spec.name, color: "--brand", width: 2.2, values: se.equity.map(tr) }];
        if (se.benchmark) series.push({ name: t("st_bench") + " · " + r.benchmark.label, color: "--text-3", width: 1.4, dash: "5 4", values: se.benchmark.map(tr) });
        var vlines = r.spec.oos_start ? [{ x: Date.parse(r.spec.oos_start), label: t("st_oos_line"), color: "--warn" }] : [];
        var eqHost = paint(chartBox(t("st_equity_h"), "st-chart-tall"), { type: "line", xKind: "time", xs: xs, series: series, height: 320, legend: true, markers: false, finance: false, vlines: vlines,
            yFmt: function (v, d) { return useLog ? money(Math.pow(10, v)) : money(v); }, tipFmt: function (v) { return useLog ? money(Math.pow(10, v)) : money(v); } });
        var ddSeries = [{ name: r.spec.name, color: "--neg", width: 1.6, values: se.drawdown.map(function (v) { return v * 100; }) }];
        if (se.bench_drawdown) ddSeries.push({ name: t("st_bench"), color: "--text-3", width: 1.2, dash: "5 4", values: se.bench_drawdown.map(function (v) { return v * 100; }) });
        var ddHost = paint(chartBox(t("st_dd_h")), { type: "line", xKind: "time", xs: xs, series: ddSeries, height: 180, legend: true, markers: false, finance: false, vlines: vlines,
            yFmt: function (v, d) { return fmt(v, d) + " %"; }, tipFmt: function (v) { return fmt(v, 1) + " %"; } });
        var expHost = paint(chartBox(t("st_exposure_h")), { type: "line", xKind: "time", xs: xs, height: 160, legend: true, markers: false, finance: false,
            series: [{ name: t("st_gross"), color: "--brand", width: 1.4, values: se.gross.map(function (v) { return v * 100; }) }, { name: t("st_net"), color: "--pos", width: 1.4, values: se.net.map(function (v) { return v * 100; }) }],
            yFmt: function (v, d) { return fmt(v, d) + " %"; }, tipFmt: function (v) { return fmt(v, 0) + " %"; } });
        var annual = r.periodic.annual, years = Object.keys(annual);
        var annHost = paint(chartBox(t("st_annual_h")), { type: "bar", values: years.map(function (y) { return annual[y] === null ? null : annual[y] * 100; }), labels: years, height: 180,
            yFmt: function (v, d) { return fmt(v, d) + " %"; }, tipFmt: function (v) { return fmt(v, 1) + " %"; } });
        var ro = r.rolling;
        var rollHost = ro.dates.length ? paint(chartBox(t("st_rolling_h")), { type: "line", xKind: "time", xs: ro.dates.map(function (d) { return Date.parse(d); }), height: 180, legend: true, markers: false, finance: false,
            series: [{ name: t("st_roll_ret"), color: "--brand", width: 1.5, values: ro.ret.map(function (v) { return v === null ? null : v * 100; }) }],
            hlines: [{ y: 0 }], yFmt: function (v, d) { return fmt(v, d) + " %"; }, tipFmt: function (v) { return fmt(v, 1) + " %"; } }) : null;
        var al = r.allocation;
        var allocHost = al.symbols.length ? paint(chartBox(t("st_alloc_h")), { type: "line", xKind: "time", xs: al.dates.map(function (d) { return Date.parse(d); }), height: 200, legend: true, markers: false, finance: false,
            series: al.symbols.map(function (s, i) { return { name: s, color: PALETTE[i % PALETTE.length], width: 1.4, values: al.weights.map(function (row) { return row[i] * 100; }) }; }),
            yFmt: function (v, d) { return fmt(v, d) + " %"; }, tipFmt: function (v) { return fmt(v, 1) + " %"; } }) : null;
        var logToggle = h("label", { class: "st-check" }, [h("input", { type: "checkbox", checked: useLog, onchange: function (e) { state.logScale = e.target.checked; renderResult(); } }), t("st_log")]);
        return h("div", { class: "st-pane" }, [
            h("div", { class: "st-pane-h" }, [h("h3", { text: t("st_equity_h") }), logToggle]), eqHost, hint(t("st_equity_hint", { c: money(cap) })),
            h("h3", { text: t("st_dd_h") }), ddHost,
            h("div", { class: "st-two" }, [h("div", {}, [h("h3", { text: t("st_annual_h") }), annHost]), h("div", {}, [h("h3", { text: t("st_exposure_h") }), expHost])]),
            h("h3", { text: t("st_monthly_h") }), monthlyTable(r.periodic),
            rollHost ? h("h3", { text: t("st_rolling_h") }) : null, rollHost,
            allocHost ? h("h3", { text: t("st_alloc_h") }) : null, allocHost, allocHost && al.other.some(function (v) { return v > 0.001; }) ? hint(t("st_alloc_other")) : null]);
    }

    function monthlyTable(p) {
        var years = Object.keys(p.monthly).sort();
        var all = [];
        years.forEach(function (y) { p.monthly[y].forEach(function (v) { if (v !== null) all.push(v); }); });
        var lo = all.length ? Math.min.apply(null, all) : 0, hi = all.length ? Math.max.apply(null, all) : 0;
        var head = h("tr", {}, [h("th", { text: t("st_year") })].concat([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map(function (m) { return h("th", { class: "n", text: t("st_m" + m) }); })).concat([h("th", { class: "n", text: t("st_year_total") })]));
        var rows = years.map(function (y) {
            return h("tr", {}, [h("th", { text: y })].concat(p.monthly[y].map(function (v) {
                var k = signedIntensity(v, lo, hi);
                return h("td", { class: "n st-heat", style: "--heat:" + Math.round(Math.abs(k) * 70) + "%;--heat-col:var(" + (k >= 0 ? "--pos" : "--neg") + ")", text: v === null ? "" : fmt(v * 100, 1) });
            })).concat([h("td", { class: "n st-year-total", text: pct(p.annual[y]) })]));
        });
        return h("div", { class: "table-scroll" }, [h("table", { class: "data-table st-monthly" }, [h("thead", {}, [head]), h("tbody", {}, rows)])]);
    }

    function tradesTab(r) {
        var ts = r.trade_stats || {};
        var stats = h("dl", { class: "st-metrics" }, [["st_t_count", fmt(ts.count || 0, 0)], ["st_t_win", pct(ts.win_rate)], ["st_t_avg", pct(ts.avg_return, 2)], ["st_t_median", pct(ts.median_return, 2)],
            ["st_t_avg_win", money(ts.avg_win)], ["st_t_avg_loss", money(ts.avg_loss)], ["st_t_pf", num(ts.profit_factor)], ["st_t_expect", money(ts.expectancy)],
            ["st_t_days", fmt(ts.avg_days, 1)], ["st_t_best", pct(ts.best)], ["st_t_worst", pct(ts.worst)], ["st_t_streak", fmt(ts.max_losing_streak, 0)]].reduce(function (acc, row) {
            return acc.concat([h("dt", { text: t(row[0]) }), h("dd", { text: row[1] })]);
        }, []));
        var contrib = r.contributions.slice(0, 30);
        var cHost = contrib.length > 1 ? paint(chartBox(t("st_contrib_h")), { type: "bar", values: contrib.map(function (c) { return c.pnl; }), labels: contrib.map(function (c) { return c.symbol; }), height: 200,
            yFmt: function (v) { return money(v); }, tipFmt: function (v) { return money(v); } }) : null;
        var symbols = [""].concat(Array.from(new Set(r.trades.map(function (x) { return x.symbol; }))).sort());
        var filter = h("select", { class: "st-input st-narrow", "aria-label": t("st_filter"), onchange: function (e) { state.tradeFilter = e.target.value; renderResult(); } },
            symbols.map(function (s) { return h("option", { value: s, selected: s === state.tradeFilter, text: s || t("st_all") }); }));
        var list = r.trades.filter(function (x) { return !state.tradeFilter || x.symbol === state.tradeFilter; });
        var key = state.tradeSort;
        list = list.slice().sort(function (a, b) {
            var va = a[key], vb = b[key];
            if (key === "entry") return va < vb ? 1 : -1;
            return (vb === null ? -Infinity : vb) - (va === null ? -Infinity : va);
        });
        function th(k, label, cls) { return h("th", { class: (cls || "") + " st-sort" + (key === k ? " is-on" : ""), tabindex: "0", text: label, onclick: function () { state.tradeSort = k; renderResult(); } }); }
        var head = h("tr", {}, [th("symbol", t("st_col_symbol")), th("side", t("st_col_side")), th("entry", t("st_col_entry")), h("th", { text: t("st_col_exit") }),
            th("days", t("st_col_days"), "n"), th("return", t("st_col_return"), "n"), th("pnl", t("st_col_pnl"), "n"), th("costs", t("st_col_costs"), "n"), h("th", { text: t("st_col_reason") })]);
        var rows = list.slice(0, 500).map(function (x) {
            return h("tr", {}, [h("td", { text: x.symbol }), h("td", { text: x.side > 0 ? t("st_long") : t("st_short") }), h("td", { text: x.entry + " · " + fmt(x.entry_price, 2) }),
                h("td", { text: (x.exit || t("st_open")) + " · " + fmt(x.exit_price, 2) }), h("td", { class: "n", text: fmt(x.days, 0) }),
                h("td", { class: "n " + (x.return >= 0 ? "pos" : "neg"), text: pct(x.return, 2) }), h("td", { class: "n " + (x.pnl >= 0 ? "pos" : "neg"), text: money(x.pnl) }),
                h("td", { class: "n", text: money(x.costs) }), h("td", { text: x.reason })]);
        });
        var csv = h("button", { type: "button", class: "btn-secondary st-small", text: t("st_export_trades"), onclick: function () { download("operations.csv", tradesCsv(r.trades)); } });
        var byYear = r.costs.by_year;
        return h("div", { class: "st-pane" }, [h("h3", { text: t("st_trade_stats_h") }), stats,
            cHost ? h("h3", { text: t("st_contrib_h") }) : null, cHost,
            h("div", { class: "st-pane-h" }, [h("h3", { text: t("st_trades_h", { n: r.trades_total }) }), filter, csv]),
            r.trades_total > r.trades.length ? hint(t("st_trades_cut", { n: r.trades.length })) : null,
            h("div", { class: "table-scroll st-trades" }, [h("table", { class: "data-table" }, [h("thead", {}, [head]), h("tbody", {}, rows)])]),
            list.length > 500 ? hint(t("st_trades_more", { n: list.length - 500 })) : null,
            h("h3", { text: t("st_costs_year_h") }),
            h("p", { class: "hint", text: Object.keys(byYear).map(function (y) { return y + " : " + money(byYear[y]); }).join(" · ") || "—" })]);
    }

    function riskTab(r) {
        var s = r.summary, b = r.benchmark && r.benchmark.metrics;
        var rows = [["st_r_total", "total_return", pct], ["st_r_cagr", "cagr", pct], ["st_r_vol", "vol", pct], ["st_r_sharpe", "sharpe", num], ["st_r_sortino", "sortino", num],
            ["st_r_calmar", "calmar", num], ["st_r_mdd", "max_dd", pct], ["st_r_longest", "longest_dd_days", function (v) { return fmt(v, 0); }], ["st_r_best_day", "best_day", pct],
            ["st_r_worst_day", "worst_day", pct], ["st_r_var", "var95", function (v) { return pct(v, 2); }], ["st_r_cvar", "cvar95", function (v) { return pct(v, 2); }],
            ["st_r_skew", "skew", num], ["st_r_kurt", "kurtosis", num], ["st_r_hit", "hit_days", pct]];
        var head = h("tr", {}, [h("th", { text: "" }), h("th", { class: "n", text: r.spec.name }), b ? h("th", { class: "n", text: t("st_bench") + " · " + r.benchmark.label }) : null]);
        var body = rows.map(function (row) {
            return h("tr", {}, [h("td", { text: t(row[0]) }), h("td", { class: "n", text: row[2](s[row[1]]) }), b ? h("td", { class: "n", text: row[2](b[row[1]]) }) : null]);
        });
        var vs = (r.benchmark && r.benchmark.versus) || {};
        var vsList = Object.keys(vs).length ? h("dl", { class: "st-metrics" }, [["st_vs_beta", num(vs.beta)], ["st_vs_alpha", pct(vs.alpha)], ["st_vs_corr", num(vs.correlation)],
            ["st_vs_te", pct(vs.tracking_error)], ["st_vs_ir", num(vs.information_ratio)], ["st_vs_up", pct(vs.up_capture, 0)], ["st_vs_down", pct(vs.down_capture, 0)]].reduce(function (acc, x) {
            return acc.concat([h("dt", { text: t(x[0]) }), h("dd", { text: x[1] })]);
        }, [])) : null;
        var dd = h("table", { class: "data-table" }, [h("thead", {}, [h("tr", {}, [t("st_dd_start"), t("st_dd_trough"), t("st_dd_end"), t("st_dd_depth"), t("st_dd_days")].map(function (c, i) { return h("th", { class: i > 2 ? "n" : "", text: c }); }))]),
            h("tbody", {}, r.drawdowns.map(function (d) {
                return h("tr", {}, [h("td", { text: d.start }), h("td", { text: d.trough }), h("td", { text: d.end || t("st_not_recovered") }), h("td", { class: "n neg", text: pct(d.depth) }), h("td", { class: "n", text: fmt(d.days_total, 0) })]);
            }))]);
        var uni = h("table", { class: "data-table" }, [h("thead", {}, [h("tr", {}, [t("st_col_symbol"), t("st_col_first"), t("st_col_last"), t("st_col_source")].map(function (c) { return h("th", { text: c }); }))]),
            h("tbody", {}, r.universe.map(function (u) { return h("tr", {}, [h("td", { text: u.symbol }), h("td", { text: u.first }), h("td", { text: u.last }), h("td", { text: u.source })]); }))]);
        return h("div", { class: "st-pane" }, [h("h3", { text: t("st_risk_h") }), h("div", { class: "table-scroll" }, [h("table", { class: "data-table" }, [h("thead", {}, [head]), h("tbody", {}, body)])]),
            vsList ? h("h3", { text: t("st_vs_h") }) : null, vsList, vsList ? hint(t("st_vs_hint")) : null,
            h("h3", { text: t("st_dd_table_h") }), h("div", { class: "table-scroll" }, [dd]),
            h("h3", { text: t("st_universe_used") }), h("div", { class: "table-scroll" }, [uni]),
            r.missing.length ? h("p", { class: "st-error", text: t("st_missing", { s: r.missing.join(", ") }) }) : null]);
    }

    function robustTab(r) {
        var rb = r.robustness, parts = [];
        var sp = rb.split;
        if (sp && sp.in_sample) {
            var rows = [["st_r_cagr", "cagr", pct], ["st_r_sharpe", "sharpe", num], ["st_r_mdd", "max_dd", pct], ["st_r_vol", "vol", pct]];
            parts.push(h("h3", { text: t("st_split_h", { d: sp.oos_start }) }));
            parts.push(h("div", { class: "table-scroll" }, [h("table", { class: "data-table" }, [h("thead", {}, [h("tr", {}, [h("th", {}), h("th", { class: "n", text: t("st_in_sample") }), h("th", { class: "n", text: t("st_out_sample") })])]),
                h("tbody", {}, rows.map(function (x) { return h("tr", {}, [h("td", { text: t(x[0]) }), h("td", { class: "n", text: x[2](sp.in_sample[x[1]]) }), h("td", { class: "n", text: x[2](sp.out_of_sample[x[1]]) })]); }))])]));
            parts.push(hint(t("st_split_hint")));
        } else if (sp && sp.error) parts.push(hint(sp.error));
        else parts.push(hint(t("st_split_none")));
        var rd = rb.random;
        if (rd && rd.available) {
            var centers = rd.hist.edges.slice(0, -1).map(function (e, i) { return (e + rd.hist.edges[i + 1]) / 2; });
            var strong = centers.map(function (c) { return c >= rd.actual; });
            parts.push(h("h3", { text: t("st_random_h") }));
            parts.push(paint(chartBox(t("st_random_h")), { type: "bar", values: rd.hist.counts, labels: centers.map(function (c) { return num(c); }), strong: strong, height: 180,
                color: function () { return "--text-3"; }, yFmt: function (v) { return fmt(v, 0); }, tipFmt: function (v) { return fmt(v, 0); } }));
            parts.push(hint(t("st_random_line", { a: num(rd.actual), p: num(rd.p_value, 3), m: num(rd.percentiles["50"]), q: num(rd.percentiles["95"]), n: rd.n })));
        } else parts.push(hint(t("st_random_none")));
        var cs = rb.costs;
        if (cs) {
            parts.push(h("h3", { text: t("st_costsens_h") }));
            parts.push(paint(chartBox(t("st_costsens_h")), { type: "line", xKind: "index", xs: cs.rows.map(function (x) { return x.mult; }), height: 180, legend: true, markers: true, finance: false, zoomable: false,
                xLabel: function (x) { return "×" + fmt(x, x % 1 ? 1 : 0); }, hlines: [{ y: 0 }],
                series: [{ name: t("st_r_sharpe"), color: "--brand", width: 2, values: cs.rows.map(function (x) { return x.sharpe; }) }],
                yFmt: function (v, d) { return fmt(v, d); }, tipFmt: function (v) { return num(v); } }));
            parts.push(hint(t("st_costsens_line", { b: cs.breakeven_sharpe === null ? t("st_never") : "×" + num(cs.breakeven_sharpe, 1), c: cs.breakeven_benchmark === null ? t("st_never") : "×" + num(cs.breakeven_benchmark, 1), y: pct(cs.annual_cost, 2) })));
        }
        var bs = rb.bootstrap;
        if (bs && bs.available) {
            parts.push(h("h3", { text: t("st_boot_h") }));
            parts.push(h("div", { class: "table-scroll" }, [h("table", { class: "data-table" }, [h("thead", {}, [h("tr", {}, ["", "P5", "P50", "P95"].map(function (c, i) { return h("th", { class: i ? "n" : "", text: c }); }))]),
                h("tbody", {}, [["st_r_cagr", bs.cagr, pct], ["st_r_sharpe", bs.sharpe, num], ["st_r_mdd", bs.max_dd, pct]].map(function (x) {
                    return h("tr", {}, [h("td", { text: t(x[0]) }), h("td", { class: "n", text: x[2](x[1].p05) }), h("td", { class: "n", text: x[2](x[1].p50) }), h("td", { class: "n", text: x[2](x[1].p95) })]);
                }))])]));
            parts.push(hint(t("st_boot_line", { p: pct(bs.prob_loss, 0), n: bs.n })));
        }
        parts.push(hint(t("st_psr_line", { p: rb.psr === null ? "—" : pct(rb.psr, 0) }) + (rb.dsr ? " · " + t("st_dsr_line", { p: rb.dsr.dsr === null ? "—" : pct(rb.dsr.dsr, 0), n: rb.dsr.trials, s: num(rb.dsr.sr0_annual) }) : "")));
        var g = rb.grid;
        if (g) {
            var mx = gridMatrix(g, "sharpe");
            if (mx) {
                parts.push(h("h3", { text: t("st_grid_h") }));
                var params = r.spec.params;
                var head = h("tr", {}, [h("th", { text: mx.y ? t("st_p_" + mx.y.param) + " \\ " + t("st_p_" + mx.x.param) : t("st_p_" + mx.x.param) })].concat(mx.x.values.map(function (v) { return h("th", { class: "n", text: String(v) }); })));
                var rowsG = mx.rows.map(function (row, i) {
                    var yv = mx.y ? mx.y.values[i] : null;
                    return h("tr", {}, [h("th", { text: mx.y ? String(yv) : t("st_r_sharpe") })].concat(row.map(function (v, j) {
                        var k = signedIntensity(v, mx.min, mx.max);
                        var mine = params[mx.x.param] === mx.x.values[j] && (!mx.y || params[mx.y.param] === yv);
                        return h("td", { class: "n st-heat" + (mine ? " st-mine" : ""), style: "--heat:" + Math.round(Math.abs(k) * 70) + "%;--heat-col:var(" + (k >= 0 ? "--pos" : "--neg") + ")", text: v === null ? "—" : num(v) });
                    })));
                });
                parts.push(h("div", { class: "table-scroll" }, [h("table", { class: "data-table st-grid" }, [h("thead", {}, [head]), h("tbody", {}, rowsG)])]));
                parts.push(hint(t("st_grid_line", { p: g.plateau === null ? "—" : pct(g.plateau, 0) })));
                if (g.pbo && g.pbo.pbo !== null) parts.push(hint(t("st_pbo_line", { p: pct(g.pbo.pbo, 0), n: g.pbo.n_trials, b: g.pbo.n_blocks })));
            }
            if (g.walk_forward) {
                var wf = g.walk_forward;
                parts.push(h("h3", { text: t("st_wf_h") }));
                parts.push(paint(chartBox(t("st_wf_h")), { type: "line", xKind: "time", xs: wf.dates.map(function (d) { return Date.parse(d); }), height: 180, legend: false, markers: false, finance: false,
                    series: [{ name: t("st_wf_h"), color: "--brand", width: 1.8, values: wf.equity.map(function (v) { return v * 100; }) }], yFmt: function (v, d) { return fmt(v, d); }, tipFmt: function (v) { return fmt(v, 1); } }));
                parts.push(hint(t("st_wf_line", { c: pct(wf.metrics.cagr), s: num(wf.metrics.sharpe), d: pct(wf.metrics.max_dd), since: wf.start })));
                parts.push(hint(wf.chosen.map(function (x) { return x.year + " : " + x.label; }).join(" · ")));
            }
        }
        return h("div", { class: "st-pane" }, [hint(t("st_robust_intro"))].concat(parts));
    }

    function compareTab() {
        var runs = state.runs;
        if (!runs.length) return h("div", { class: "st-pane" }, [hint(t("st_no_runs"))]);
        if (!state.compare.length && state.runId) state.compare = [state.runId];
        var chosen = runs.filter(function (x) { return state.compare.indexOf(x.id) >= 0; });
        var all = {};
        chosen.forEach(function (x) { x.curve.dates.forEach(function (d) { all[d] = 1; }); });
        var dates = Object.keys(all).sort();
        var series = chosen.map(function (x, i) {
            var map = {};
            x.curve.dates.forEach(function (d, j) { map[d] = x.curve.equity[j]; });
            var last = null;
            var vals = dates.map(function (d) { if (map[d] !== undefined) last = map[d]; return d >= x.curve.dates[0] ? last : null; });
            return { name: x.name, color: PALETTE[i % PALETTE.length], width: 1.8, values: rebase(vals) };
        });
        var chart = chosen.length ? paint(chartBox(t("st_compare_h"), "st-chart-tall"), { type: "line", xKind: "time", xs: dates.map(function (d) { return Date.parse(d); }), series: series, height: 300, legend: true, markers: false, finance: false,
            yFmt: function (v, d) { return fmt(v, d); }, tipFmt: function (v) { return fmt(v, 1); } }) : hint(t("st_compare_pick"));
        var head = h("tr", {}, ["", t("st_col_name"), t("st_col_tpl"), t("st_col_period"), t("st_r_cagr"), t("st_r_sharpe"), t("st_r_mdd"), t("st_k_trades"), t("st_col_verdict"), ""].map(function (c, i) { return h("th", { class: i > 3 && i < 8 ? "n" : "", text: c }); }));
        var rows = runs.map(function (x) {
            var on = state.compare.indexOf(x.id) >= 0;
            return h("tr", { class: x.id === state.runId ? "is-on" : "" }, [
                h("td", {}, [h("input", { type: "checkbox", checked: on, "aria-label": t("st_compare_this") + " " + x.name, onchange: function (e) {
                    if (e.target.checked) state.compare.push(x.id); else state.compare = state.compare.filter(function (id) { return id !== x.id; }); renderResult();
                } })]),
                h("td", {}, [h("button", { type: "button", class: "st-link", text: (x.pinned ? "★ " : "") + x.name, onclick: function () { loadRun(x.id); } })]),
                h("td", { text: t("st_tpl_" + x.template) }), h("td", { text: x.start.slice(0, 4) + "–" + x.end.slice(0, 4) + " · " + x.n_symbols }),
                h("td", { class: "n", text: pct(x.cagr) }), h("td", { class: "n", text: num(x.sharpe) }), h("td", { class: "n", text: pct(x.max_dd) }), h("td", { class: "n", text: fmt(x.trades, 0) }),
                h("td", {}, [badge(t("st_v_" + x.verdict), verdictTone(x.verdict))]),
                h("td", { class: "st-actions" }, [
                    h("button", { type: "button", class: "btn-secondary st-small", title: t("st_pin"), "aria-label": t("st_pin"), text: x.pinned ? "★" : "☆", onclick: function () { call("POST", "/api/strategies/runs/" + x.id, { pinned: !x.pinned }).then(loadRuns).then(renderResult); } }),
                    h("button", { type: "button", class: "btn-secondary st-small", title: t("st_rename"), "aria-label": t("st_rename"), text: "✎", onclick: function () {
                        var n = root.prompt(t("st_rename"), x.name); if (n) call("POST", "/api/strategies/runs/" + x.id, { name: n }).then(loadRuns).then(renderResult);
                    } }),
                    h("button", { type: "button", class: "btn-secondary st-small", title: t("st_delete"), "aria-label": t("st_delete"), text: "✕", onclick: function () {
                        if (!root.confirm(t("st_delete_confirm"))) return;
                        call("DELETE", "/api/strategies/runs/" + x.id).then(function () { state.compare = state.compare.filter(function (id) { return id !== x.id; }); return loadRuns(); }).then(renderResult);
                    } })])]);
        });
        return h("div", { class: "st-pane" }, [chart, h("div", { class: "table-scroll" }, [h("table", { class: "data-table st-compare" }, [h("thead", {}, [head]), h("tbody", {}, rows)])]), hint(t("st_compare_hint"))]);
    }

    function rulesSummary(r) {
        var s = r.strategy, lines = [];
        RULE_KEYS.forEach(function (k) { if (s[k]) lines.push(h("li", {}, [h("strong", { text: t("st_rule_" + k) + " : " }), groupText(s[k], t)])); });
        if (s.selection) lines.push(h("li", {}, [h("strong", { text: t("st_selection_on") + " : " }), t("st_sel_line", { top: s.selection.top, bottom: s.selection.bottom || 0, by: operandText(s.selection.rank_by, t) })]));
        if (!lines.length) lines.push(h("li", { text: t("st_rules_always") }));
        lines.push(h("li", { class: "hint", text: t("st_run_line", { d: t("st_opt_" + s.decision), r: t("st_opt_" + s.rebalance), m: t("st_opt_" + (s.sizing.method || "equal")) }) }));
        return h("ul", { class: "st-rule-list" }, lines);
    }

    function renderResult() {
        var r = state.result;
        if (!r) { els.result.hidden = true; return; }
        els.result.hidden = false;
        var box = clear(els.resultBody);
        box.appendChild(h("div", { class: "st-result-h" }, [h("div", {}, [h("h2", { text: r.spec.name }),
            h("p", { class: "hint", text: t("st_result_line", { a: r.period.start, b: r.period.end, n: r.universe.length, tpl: t("st_tpl_" + r.spec.template) }) })]),
            h("button", { type: "button", class: "btn-secondary st-small", text: t("st_reload_form"), onclick: function () { loadSpec(r.spec); } })]));
        box.appendChild(rulesSummary(r));
        if (r.notes && r.notes.length) box.appendChild(h("ul", { class: "st-notes" }, r.notes.map(function (n) { return h("li", { text: n }); })));
        box.appendChild(verdictBlock(r));
        box.appendChild(kpis(r));
        box.appendChild(tabs(r));
        var pane = { perf: perfTab, trades: tradesTab, risk: riskTab, robust: robustTab, compare: compareTab }[state.tab](r);
        box.appendChild(pane);
    }

    function renderHistory() {
        if (!els.history) return;
        clear(els.history);
        if (!state.runs.length) { els.history.appendChild(hint(t("st_no_runs"))); return; }
        var sel = h("select", { class: "st-input", "aria-label": t("st_history"), onchange: function (e) { if (e.target.value) loadRun(e.target.value); } },
            [h("option", { value: "", text: t("st_history_pick", { n: state.runs.length }) })].concat(state.runs.map(function (x) {
                return h("option", { value: x.id, selected: x.id === state.runId, text: (x.pinned ? "★ " : "") + x.name + " · " + x.created.slice(0, 10) + " · " + t("st_v_" + x.verdict) });
            })));
        els.history.appendChild(sel);
    }

    Promise.all([call("GET", "/api/strategies/catalog"), root.fetch("/api/asset-index").then(function (r) { return r.ok ? r.json() : []; }).catch(function () { return []; })])
        .then(function (res) {
            state.catalog = res[0]; state.assets = res[1] || [];
            renderForm();
            return loadRuns().then(function () { if (state.runs.length) return loadRun(state.runs[0].id, true); });
        }).catch(function (e) { clear(els.form).appendChild(h("p", { class: "st-error", text: e.message })); });
})(typeof window !== "undefined" ? window : globalThis);
