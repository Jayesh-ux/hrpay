import { registry } from "@web/core/registry";
import { router, routerBus } from "@web/core/browser/router";
import { useBus, useService } from "@web/core/utils/hooks";
import { Component, onWillDestroy, reactive, useState, xml } from "@odoo/owl";

// ============================================================================
// HRMS theme enhancement module (styling only — no business logic).
//
//   * Applies the dark navy + violet theme as a class on <html> as early as the
//     bundle is evaluated (no flash). Odoo's SCSS greys are compiled dark in
//     primary_variables.scss, so a light variant is intentionally not offered.
//   * Registers a detailed, collapsible left navigation built from Odoo's own
//     menu service, so every menu of the current app is reachable in one place.
// ============================================================================

function applyTheme() {
    const root = document.documentElement;
    root.classList.add("hrms-dark");
    root.classList.remove("hrms-light");
}

// <html> always exists while the bundle is evaluated, so the theme class is set
// before first paint and there is no flash of the wrong palette. A stale
// `hrms_theme` localStorage value from earlier builds is deliberately ignored.
applyTheme();

// --- Left navigation: two panels --------------------------------------------
//
//   Panel 1 (`HrmsAppRail`)   — the installed applications, always visible on
//                               desktop. App metadata (names, icons, actions,
//                               and permission filtering) comes straight from
//                               Odoo's `menu` service via `getApps()`, so there
//                               is no hand-maintained app list.
//   Panel 2 (`HrmsSidebar`)   — the current app's full nested menu tree, exactly
//                               as before.
//
// Both panels are pure Client Components placed in `main_components`. The only
// shared state is the collapsed flag for Panel 2, kept module-scoped and mirrored
// as a class on <html> so the workspace reflows without any JS layout math.

const navUi = reactive({ navCollapsed: false });

function applyNavClass() {
    document.documentElement.classList.toggle("hrms-nav-collapsed", navUi.navCollapsed);
}

function toggleNavPanel() {
    navUi.navCollapsed = !navUi.navCollapsed;
    applyNavClass();
}

// Controlled multicolor palette for icon tiles and section markers. Vivid but
// used only on small focal points over the neutral dark foundation (never as
// large background areas), per the Liquid Glass brief.
const HRMS_COLORS = [
    "#8b5cf6", // purple
    "#22d3ee", // cyan
    "#34d399", // green
    "#fb923c", // orange
    "#f472b6", // pink
    "#fbbf24", // amber
    "#2dd4bf", // teal
    "#f87171", // red
    "#a78bfa", // light purple
    "#4ade80", // lime
];

function colorFor(seed) {
    const s = String(seed || "");
    let h = 0;
    for (let i = 0; i < s.length; i++) {
        h = (h * 31 + s.charCodeAt(i)) >>> 0;
    }
    return HRMS_COLORS[h % HRMS_COLORS.length];
}

// Panel 1 — application navigation rail.
class HrmsAppRail extends Component {
    static template = xml`
        <aside class="hrms-apprail" aria-label="Applications">
            <div class="hrms-apprail__head">
                <button type="button" class="hrms-apprail__menu"
                        title="Toggle navigation panel"
                        t-att-aria-expanded="this.collapsed ? 'false' : 'true'"
                        t-on-click="() => this.toggleNav()">
                    <i class="fa fa-bars" aria-hidden="true"/>
                </button>
            </div>
            <nav class="hrms-apprail__list" aria-label="Applications">
                <button t-foreach="this.apps" t-as="app" t-key="app.id" type="button"
                        class="hrms-apprail__app"
                        t-att-class="{ 'is-active': this.isActive(app) }"
                        t-att-aria-current="this.isActive(app) ? 'page' : undefined"
                        t-att-title="app.name"
                        t-attf-style="--hrms-app-color: {{ this.appColor(app) }}"
                        t-on-click="() => this.selectApp(app)">
                    <span class="hrms-apprail__iconwrap" aria-hidden="true">
                        <img t-if="this.hasRealIcon(app)" class="hrms-apprail__icon"
                             t-att-src="app.webIconData" alt=""/>
                        <span t-else="" class="hrms-apprail__icon hrms-apprail__icon--mono"
                              t-esc="this.initial(app)"/>
                    </span>
                    <span class="hrms-apprail__label" t-esc="app.name"/>
                </button>
            </nav>
        </aside>`;

    setup() {
        this.menuService = useService("menu");
        this.state = useState({ activeAppId: null });

        // Re-sync whenever the active app changes or the route moves.
        useBus(this.env.bus, "MENUS:APP-CHANGED", () => this.syncActive());
        this.onRouteChange = () => this.syncActive();
        routerBus.addEventListener("ROUTE_CHANGE", this.onRouteChange);
        onWillDestroy(() => routerBus.removeEventListener("ROUTE_CHANGE", this.onRouteChange));
        this.syncActive();
    }

    get apps() {
        return this.menuService.getApps();
    }

    get collapsed() {
        return navUi.navCollapsed;
    }

    syncActive() {
        const app = this.menuService.getCurrentApp();
        this.state.activeAppId = app ? app.id : null;
    }

    initial(app) {
        return ((app && app.name) || "?").trim().slice(0, 1).toUpperCase();
    }

    // A custom app icon is served as a data URI; the many apps without a bespoke
    // icon share one generic placeholder, so those get a colourful initial tile
    // instead (recognizable + distinct, and no fake imagery).
    hasRealIcon(app) {
        return typeof app.webIconData === "string" && app.webIconData.startsWith("data:");
    }

    appColor(app) {
        const i = this.apps.findIndex((a) => a.id === app.id);
        return HRMS_COLORS[(i >= 0 ? i : colorFor(app.name).length) % HRMS_COLORS.length];
    }

    isActive(app) {
        return this.state.activeAppId === app.id;
    }

    toggleNav() {
        toggleNavPanel();
    }

    async selectApp(app) {
        // `selectMenu` performs Odoo's own SPA navigation for the app's action,
        // so permissions and the real action/route are honoured.
        await this.menuService.selectMenu(app);
        this.syncActive();
    }
}

// Panel 2 — the current application's navigation.
class HrmsSidebar extends Component {
    static template = xml`
        <aside class="hrms-sidebar">
            <div class="hrms-sidebar__head">
                <t t-if="this.app">
                    <img t-if="this.app.webIconData" class="hrms-sidebar__app-icon"
                         t-att-src="this.app.webIconData" alt=""/>
                    <span t-else="" class="hrms-sidebar__app-icon hrms-sidebar__app-icon--mono"
                          t-esc="this.appInitials"/>
                    <span class="hrms-sidebar__app-name" t-esc="this.app.name"/>
                </t>
                <t t-else="">
                    <span class="hrms-sidebar__app-icon hrms-sidebar__app-icon--mono">H</span>
                    <span class="hrms-sidebar__app-name">All apps</span>
                </t>
                <button type="button" class="hrms-sidebar__collapse"
                        title="Hide navigation panel" aria-label="Hide navigation panel"
                        t-on-click="() => this.toggleNav()">
                    <i class="oi oi-close" aria-hidden="true"/>
                </button>
            </div>

            <nav class="hrms-sidebar__nav" aria-label="Menu">
                <div t-foreach="this.groups" t-as="group" t-key="group.node.id"
                     class="hrms-nav-group"
                     t-attf-style="--hrms-group-color: {{ this.groupColor(group) }}">
                    <t t-if="group.isGroup">
                        <button type="button" class="hrms-nav-group__title"
                                t-on-click="() => this.toggle(group.node.id)">
                            <span class="hrms-nav-group__dot" aria-hidden="true"/>
                            <span class="hrms-nav-group__name" t-esc="group.node.name"/>
                            <i class="fa" t-att-class="this.isOpen(group.node.id) ? 'fa-angle-up' : 'fa-angle-down'"
                               aria-hidden="true"/>
                        </button>
                        <ul t-if="this.isOpen(group.node.id)" class="hrms-nav-group__list">
                            <li t-foreach="this.flatten(group.children)" t-as="item" t-key="item.node.id"
                                class="hrms-nav-item"
                                t-att-class="{ 'is-active': this.isActive(item.node) }">
                                <a t-if="item.node.actionID" class="hrms-nav-item__link"
                                   t-att-href="this.href(item.node)"
                                   t-att-style="'--hrms-depth:' + item.depth"
                                   t-on-click.prevent="(ev) => this.onClick(ev, item.node)">
                                    <span class="hrms-nav-item__marker"/>
                                    <span class="hrms-nav-item__text" t-esc="item.node.name"/>
                                </a>
                                <span t-else="" class="hrms-nav-item__link hrms-nav-item__link--static"
                                      t-att-style="'--hrms-depth:' + item.depth">
                                    <span class="hrms-nav-item__marker"/>
                                    <span class="hrms-nav-item__text" t-esc="item.node.name"/>
                                </span>
                            </li>
                        </ul>
                    </t>
                    <t t-else="">
                        <a t-if="group.node.actionID" class="hrms-nav-item__link hrms-nav-item__link--solo"
                           t-att-class="{ 'is-active': this.isActive(group.node) }"
                           t-att-href="this.href(group.node)"
                           t-on-click.prevent="(ev) => this.onClick(ev, group.node)">
                            <span class="hrms-nav-item__marker"/>
                            <span class="hrms-nav-item__text" t-esc="group.node.name"/>
                        </a>
                        <span t-else="" class="hrms-nav-item__link hrms-nav-item__link--solo hrms-nav-item__link--static">
                            <span class="hrms-nav-item__marker"/>
                            <span class="hrms-nav-item__text" t-esc="group.node.name"/>
                        </span>
                    </t>
                </div>
            </nav>
        </aside>`;

    setup() {
        this.menuService = useService("menu");
        this.state = useState({
            collapsed: {}, // menu id -> true when the user collapsed it
            // The router stores the active action either as a numeric action id
            // (e.g. /odoo/action-435) or as an action path string.
            activeAction: router.current ? router.current.action : null,
        });

        // The current app changed: rebuild the tree.
        useBus(this.env.bus, "MENUS:APP-CHANGED", () => this.render());

        // The active action changed: update the highlighted entry.
        this.onRouteChange = () => {
            this.state.activeAction = router.current ? router.current.action : null;
        };
        routerBus.addEventListener("ROUTE_CHANGE", this.onRouteChange);
        onWillDestroy(() => routerBus.removeEventListener("ROUTE_CHANGE", this.onRouteChange));
    }

    get app() {
        return this.menuService.getCurrentApp();
    }

    get appInitials() {
        const name = (this.app && this.app.name) || "";
        return name.trim().slice(0, 1).toUpperCase();
    }

    // Top-level menus grouped for the sidebar: a section with children becomes a
    // titled group; a section that is itself an action becomes a standalone item.
    get groups() {
        const app = this.app;
        if (!app) {
            return [];
        }
        const tree = this.menuService.getMenuAsTree(app.id);
        return (tree.childrenTree || []).map((node) => {
            const children = node.childrenTree || [];
            return { node, children, isGroup: children.length > 0 };
        });
    }

    // A stable coordinated colour per top-level section (index-based so adjacent
    // sections differ), used for the section dot and the item markers.
    groupColor(group) {
        const i = this.groups.findIndex((g) => g.node.id === group.node.id);
        return colorFor("grp:" + (i >= 0 ? i : group.node.name));
    }

    // Flat list of a group's descendants with their indentation depth.
    flatten(nodes, depth = 0) {
        const out = [];
        for (const node of nodes) {
            const children = node.childrenTree || [];
            out.push({ node, depth });
            if (children.length) {
                out.push(...this.flatten(children, depth + 1));
            }
        }
        return out;
    }

    isOpen(id) {
        return this.state.collapsed[id] !== true;
    }

    toggle(id) {
        this.state.collapsed[id] = !this.state.collapsed[id];
    }

    toggleNav() {
        toggleNavPanel();
    }

    isActive(node) {
        const current = this.state.activeAction;
        if (current !== null && current !== undefined) {
            if (node.actionPath && node.actionPath === current) {
                return true;
            }
            if (
                node.actionID !== null &&
                node.actionID !== undefined &&
                String(node.actionID) === String(current)
            ) {
                return true;
            }
        }
        if (node.childrenTree && node.childrenTree.length) {
            return node.childrenTree.some((child) => this.isActive(child));
        }
        return false;
    }

    href(node) {
        return `/odoo/${node.actionPath || "action-" + node.actionID}`;
    }

    async onClick(ev, node) {
        await this.menuService.selectMenu(node);
    }
}

// Navbar breadcrumb — the real navigation path (app › section › page).
//
// Odoo's control panel only knows the leaf action, so the ancestors are derived
// from the menu tree: we walk the app's menu tree and keep the branch that
// contains the active action. Every crumb is real Odoo metadata; ancestors are
// clickable only when their menu node actually has an action. The control panel
// title and action buttons are left untouched.
class HrmsBreadcrumb extends Component {
    static template = xml`
        <nav t-if="this.trail.length" class="hrms-breadcrumb" aria-label="Breadcrumb">
            <ol class="hrms-breadcrumb__list">
                <li t-foreach="this.trail" t-as="crumb" t-key="crumb.key"
                    class="hrms-breadcrumb__item">
                    <a t-if="crumb.clickable &amp;&amp; !crumb.current"
                       class="hrms-breadcrumb__link"
                       t-att-href="this.href(crumb.node)"
                       t-on-click.prevent="(ev) => this.onClick(ev, crumb.node)">
                        <span t-esc="crumb.name"/>
                    </a>
                    <span t-else="" class="hrms-breadcrumb__current" t-esc="crumb.name"/>
                    <i t-if="!crumb.last" class="fa fa-angle-right hrms-breadcrumb__sep"
                       aria-hidden="true"/>
                </li>
            </ol>
        </nav>`;

    setup() {
        this.menuService = useService("menu");
        this.state = useState({
            // `tick` forces a recompute when the app changes but the action id
            // (and therefore the tree) stays the same.
            tick: 0,
            activeAction: router.current ? router.current.action : null,
        });

        // Switching app rebuilds the tree; route moves change the active leaf.
        useBus(this.env.bus, "MENUS:APP-CHANGED", () => this.sync());
        this.onRouteChange = () => this.sync();
        routerBus.addEventListener("ROUTE_CHANGE", this.onRouteChange);
        onWillDestroy(() => routerBus.removeEventListener("ROUTE_CHANGE", this.onRouteChange));
    }

    sync() {
        this.state.tick++;
        this.state.activeAction = router.current ? router.current.action : null;
    }

    // app › section › ... › page, derived from the real menu metadata.
    get trail() {
        // eslint-disable-next-line no-unused-expressions
        this.state.tick; // read reactive state so the trail recomputes on change
        const app = this.menuService.getCurrentApp();
        if (!app) {
            return [];
        }
        const crumbs = [
            { key: "app-" + app.id, node: app, name: app.name, clickable: !!app.actionID },
        ];
        const tree = this.menuService.getMenuAsTree(app.id);
        for (const node of this.findPath(tree.childrenTree || [])) {
            crumbs.push({ key: "menu-" + node.id, node, name: node.name, clickable: !!node.actionID });
        }
        // Drop consecutive duplicates (e.g. an app and a first section sharing a
        // name) so no incorrect/duplicate ancestor is shown.
        const deduped = crumbs.filter(
            (c, i) => i === 0 || c.name.trim() !== crumbs[i - 1].name.trim()
        );
        deduped.forEach((c, i) => {
            c.last = i === deduped.length - 1;
            c.current = c.last;
        });
        return deduped;
    }

    findPath(nodes) {
        for (const node of nodes) {
            if (this.isActive(node)) {
                return [node, ...this.findPath(node.childrenTree || [])];
            }
        }
        return [];
    }

    isActive(node) {
        const action = this.state.activeAction;
        if (action !== null && action !== undefined) {
            if (node.actionPath && node.actionPath === action) {
                return true;
            }
            if (node.actionID != null && String(node.actionID) === String(action)) {
                return true;
            }
        }
        if (node.childrenTree && node.childrenTree.length) {
            return node.childrenTree.some((child) => this.isActive(child));
        }
        return false;
    }

    href(node) {
        return `/odoo/${node.actionPath || "action-" + node.actionID}`;
    }

    async onClick(ev, node) {
        await this.menuService.selectMenu(node);
    }
}

registry.category("main_components").add("hrms_theme.app_rail", {
    Component: HrmsAppRail,
    props: {},
});

registry.category("main_components").add("hrms_theme.sidebar", {
    Component: HrmsSidebar,
    props: {},
});

registry.category("main_components").add("hrms_theme.breadcrumb", {
    Component: HrmsBreadcrumb,
    props: {},
});

// --- Motion (GSAP) ----------------------------------------------------------

function gsapReady() {
    if (!window.gsap) {
        return false;
    }
    return !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function animateAction() {
    if (!gsapReady()) {
        return;
    }
    const action = document.querySelector(".o_action_manager > .o_action");
    if (!action || action.dataset.hrmsAnimated) {
        return;
    }
    action.dataset.hrmsAnimated = "1";
    const content = action.querySelector(".o_content") || action;
    window.gsap.fromTo(
        content,
        { opacity: 0, y: 12 },
        { opacity: 1, y: 0, duration: 0.35, ease: "power2.out", clearProps: "all" }
    );

    // Stagger the first rows/cards so lists and kanbans feel alive on entry.
    const rows = action.querySelectorAll(
        ".o_list_view .o_data_row, .o_kanban_renderer .o_kanban_record"
    );
    if (rows.length) {
        window.gsap.fromTo(
            Array.from(rows).slice(0, 24),
            { opacity: 0, y: 8 },
            {
                opacity: 1,
                y: 0,
                duration: 0.28,
                ease: "power2.out",
                stagger: 0.025,
                clearProps: "all",
            }
        );
    }
}

function animateSidebar() {
    if (!gsapReady()) {
        return;
    }
    const items = document.querySelectorAll(
        ".hrms-sidebar .hrms-nav-group, .hrms-sidebar .hrms-nav-item"
    );
    if (!items.length) {
        return;
    }
    window.gsap.fromTo(
        Array.from(items).slice(0, 40),
        { opacity: 0, x: -8 },
        { opacity: 1, x: 0, duration: 0.25, ease: "power2.out", stagger: 0.012, clearProps: "all" }
    );
}

function animateOverlays() {
    if (!gsapReady()) {
        return;
    }
    for (const el of document.querySelectorAll(".modal.show .modal-dialog")) {
        if (el.dataset.hrmsAnimated) {
            continue;
        }
        el.dataset.hrmsAnimated = "1";
        window.gsap.fromTo(
            el,
            { opacity: 0, y: -16, scale: 0.98 },
            { opacity: 1, y: 0, scale: 1, duration: 0.24, ease: "power2.out", clearProps: "all" }
        );
    }
}

// Broken images: some records reference a missing filestore file and Odoo
// answers /web/image with a 500, which the browser paints as a broken-image
// glyph. Swap those for a quiet themed placeholder so rows/cards never show a
// torn image. Purely cosmetic and guarded so it runs at most once per element.
const BROKEN_IMG_PLACEHOLDER =
    "data:image/svg+xml;utf8," +
    encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">' +
            '<rect width="64" height="64" rx="12" fill="#172140"/>' +
            '<circle cx="32" cy="25" r="10" fill="#3b4670"/>' +
            '<path d="M12 56c3-12 11-18 20-18s17 6 20 18z" fill="#3b4670"/>' +
            "</svg>"
    );

function swapBrokenImage(img) {
    if (!img || img.dataset.hrmsImgFixed) {
        return;
    }
    img.dataset.hrmsImgFixed = "1";
    img.src = BROKEN_IMG_PLACEHOLDER;
}

function fixBrokenImages() {
    for (const img of document.querySelectorAll("img")) {
        if (img.complete && img.naturalWidth === 0) {
            swapBrokenImage(img);
        }
    }
}

// A single capture-phase listener catches every image load failure, whenever it
// happens (including images added later by Odoo's views).
document.addEventListener(
    "error",
    (ev) => {
        const target = ev.target;
        if (target && target.tagName === "IMG") {
            swapBrokenImage(target);
        }
    },
    true
);

let scheduled = false;
function scheduleAnimate() {
    if (scheduled) {
        return;
    }
    scheduled = true;
    window.requestAnimationFrame(() => {
        scheduled = false;
        animateAction();
        animateOverlays();
        animateSidebar();
        fixBrokenImages();
    });
}

routerBus.addEventListener("ROUTE_CHANGE", scheduleAnimate);

const observer = new MutationObserver(scheduleAnimate);
if (document.body) {
    observer.observe(document.body, { childList: true, subtree: true });
}
document.addEventListener("DOMContentLoaded", scheduleAnimate, { once: true });
