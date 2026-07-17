/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState, useEffect } from "@odoo/owl";
import { Layout } from "@web/search/layout";

export class InventoryDashboard extends Component {
    static template = "ss_inventory_dashboard.InventoryDashboard";
    static components = { Layout };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.companyService = useService("company");

        this.display = {
            controlPanel: {
                "top-left": true,
                "top-right": false,
                "bottom-left": false,
                "bottom-right": false,
            }
        };

        const currentYear = new Date().getFullYear();
        this.state = useState({
            loading: true,        // initial page load spinner
            reportLoading: false, // per-tab loading spinner
            activeTab: 'inventory_status',
            kpis: {},             // store KPI summary values
            filters: {
                company_ids: [this.companyService.currentCompany.id],
                warehouse_ids: [],
                date_from: `${currentYear}-01-01`,
                date_to: new Date().toISOString().slice(0, 10),
                category_ids: [],
                product_ids: [],
                partner_ids: [],
            },
            searchQueries: {
                inventory_status: '',
                stock_ledger: '',
                ageing_analysis: '',
                pending_po: '',
            },
            dropdowns: {
                company: { isOpen: false, search: '' },
                warehouse: { isOpen: false, search: '' },
                category: { isOpen: false, search: '' },
                product: { isOpen: false, search: '' },
                partner: { isOpen: false, search: '' },
            },
            data: {
                companies: [],
                warehouses: [],
                categories: [],
                products: [],
                partners: [],
                reports: {
                    inventory_status: [],
                    stock_ledger: [],
                    ageing_analysis: [],
                    pending_po: [],
                }
            }
        });

        // Debounce timer for filter changes
        this._debounceTimer = null;

        this.loadFilterOptions = this.loadFilterOptions.bind(this);
        this.loadActiveReport = this.loadActiveReport.bind(this);
        this.scheduleReload = this.scheduleReload.bind(this);
        this.resetFilters = this.resetFilters.bind(this);
        this.exportToExcel = this.exportToExcel.bind(this);
        this.switchTab = this.switchTab.bind(this);
        this.toggleDropdown = this.toggleDropdown.bind(this);
        this.toggleSelection = this.toggleSelection.bind(this);
        this.getFilteredList = this.getFilteredList.bind(this);
        this.getSelectedLabel = this.getSelectedLabel.bind(this);
        this.getFilteredReportData = this.getFilteredReportData.bind(this);
        this.selectAllFiltered = this.selectAllFiltered.bind(this);
        this.clearAll = this.clearAll.bind(this);

        onWillStart(async () => {
            // Step 1: Load dropdowns fast (no heavy SQL)
            await this.loadFilterOptions();
            // Step 2: Load only the active tab's report
            await this.loadActiveReport();
            this.state.loading = false;
        });

        // ── Scroll Fix: force parent Odoo containers to allow vertical scrolling ──
        useEffect(() => {
            // Walk up the DOM to find .o_action and .o_action_manager and unlock scroll
            const scrollTargets = [];
            let el = document.querySelector('.o_inventory_dashboard');
            while (el && el !== document.body) {
                el = el.parentElement;
                if (!el) break;
                const cls = el.className || '';
                if (typeof cls === 'string' && (
                    cls.includes('o_action_manager') ||
                    cls.includes('o_action') ||
                    cls.includes('o_view_controller')
                )) {
                    const prev = el.style.overflowY || '';
                    el.style.overflowY = 'auto';
                    el.style.height = 'auto';
                    scrollTargets.push({ el, prev });
                }
            }
            // Also force the main content area
            const mainContent = document.querySelector('.o_main_content');
            if (mainContent) {
                const prev = mainContent.style.overflowY || '';
                mainContent.style.overflowY = 'auto';
                scrollTargets.push({ el: mainContent, prev });
            }
            // Cleanup: restore original overflow when component unmounts
            return () => {
                scrollTargets.forEach(({ el, prev }) => {
                    el.style.overflowY = prev;
                    el.style.height = '';
                });
            };
        }, () => []);

        // Click outside to close dropdowns
        useEffect(() => {
            const handleOutsideClick = (ev) => {
                Object.keys(this.state.dropdowns).forEach(key => {
                    const el = document.getElementById(`${key}-dropdown-container`);
                    if (el && !el.contains(ev.target)) {
                        this.state.dropdowns[key].isOpen = false;
                    }
                });
            };
            document.addEventListener("mousedown", handleOutsideClick);
            return () => document.removeEventListener("mousedown", handleOutsideClick);
        }, () => []);
    }

    // ── Fast call: only fetches dropdown option lists ──────────────────────────
    async loadFilterOptions() {
        try {
            const res = await this.orm.call(
                "inventory.dashboard",
                "get_filter_options",
                [],
                { company_ids: this.state.filters.company_ids }
            );
            this.state.data.companies = res.companies || [];
            this.state.data.warehouses = res.warehouses || [];
            this.state.data.categories = res.categories || [];
            this.state.data.products = res.products || [];
            this.state.data.partners = res.partners || [];
        } catch (e) {
            console.error("Failed to load filter options:", e);
        }
    }

    // ── Lazy call: fetches only the currently visible tab's report ─────────────
    async loadActiveReport() {
        this.state.reportLoading = true;
        try {
            const tab = this.state.activeTab;
            const f = this.state.filters;
            const [reportResult, kpiResult] = await Promise.all([
                this.orm.call(
                    "inventory.dashboard",
                    "get_report_data",
                    [],
                    {
                        report_name: tab,
                        company_ids: f.company_ids,
                        warehouse_ids: f.warehouse_ids,
                        date_from: f.date_from,
                        date_to: f.date_to,
                        category_ids: f.category_ids,
                        product_ids: f.product_ids,
                        partner_ids: f.partner_ids,
                    }
                ),
                this.orm.call(
                    "inventory.dashboard",
                    "get_kpi_data",
                    [],
                    {
                        company_ids: f.company_ids,
                        warehouse_ids: f.warehouse_ids,
                        date_from: f.date_from,
                        date_to: f.date_to,
                        category_ids: f.category_ids,
                        product_ids: f.product_ids,
                        partner_ids: f.partner_ids,
                    }
                )
            ]);
            this.state.data.reports[tab] = reportResult || [];
            this.state.kpis = kpiResult || {};
        } catch (e) {
            console.error("Failed to load report data:", e);
        } finally {
            this.state.reportLoading = false;
        }
    }

    // ── Debounced reload: waits 400ms after last change before firing ──────────
    scheduleReload() {
        if (this._debounceTimer) {
            clearTimeout(this._debounceTimer);
        }
        this._debounceTimer = setTimeout(async () => {
            // Invalidate cached data for active tab so it refreshes
            this.state.data.reports[this.state.activeTab] = null;
            await this.loadActiveReport();
        }, 400);
    }

    // ── Switch tab: lazy-loads the new tab's data if not already cached ────────
    async switchTab(tabName) {
        this.state.activeTab = tabName;
        // Only fetch if not already loaded
        if (this.state.data.reports[tabName] === null ||
            this.state.data.reports[tabName] === undefined) {
            await this.loadActiveReport();
        } else if (this.state.data.reports[tabName].length === 0) {
            // Tab was never loaded yet (initial state is [])
            // Check if it's truly empty or just unloaded by checking if any other tab has data
            const hasAnyData = Object.values(this.state.data.reports)
                .some(r => r && r.length > 0);
            if (!hasAnyData || this.state.data.reports[tabName].length === 0) {
                await this.loadActiveReport();
            }
        }
    }

    // Handle Dropdown Toggles
    toggleDropdown(name) {
        Object.keys(this.state.dropdowns).forEach(key => {
            if (key !== name) this.state.dropdowns[key].isOpen = false;
        });
        this.state.dropdowns[name].isOpen = !this.state.dropdowns[name].isOpen;
    }

    // Filter Items for Search Dropdowns (capped at 100, selected items bubbled to top)
    getFilteredList(name) {
        const query = (this.state.dropdowns[name].search || '').toLowerCase();
        let items = [];
        let filterName = name + '_ids';
        if (name === 'company') {
            items = this.state.data.companies;
            filterName = 'company_ids';
        } else if (name === 'warehouse') {
            items = this.state.data.warehouses;
            filterName = 'warehouse_ids';
        } else if (name === 'category') {
            items = this.state.data.categories;
            filterName = 'category_ids';
        } else if (name === 'product') {
            items = this.state.data.products;
            filterName = 'product_ids';
        } else if (name === 'partner') {
            items = this.state.data.partners;
            filterName = 'partner_ids';
        }

        let filtered = items;
        if (query) {
            filtered = items.filter(item => {
                const nameMatch = (item.complete_name || item.name || '').toLowerCase().includes(query);
                const refMatch = (item.ref || item.default_code || '').toLowerCase().includes(query);
                return nameMatch || refMatch;
            });
        }

        // Sort selected items to the top
        const selectedIds = this.state.filters[filterName] || [];
        if (selectedIds.length > 0) {
            filtered = [...filtered].sort((a, b) => {
                const aSel = selectedIds.includes(a.id) ? 1 : 0;
                const bSel = selectedIds.includes(b.id) ? 1 : 0;
                return bSel - aSel;
            });
        }

        return filtered.slice(0, 100);
    }

    // Multiselect Item Toggles
    toggleSelection(name, id) {
        const list = this.state.filters[name];
        const idx = list.indexOf(id);
        if (idx === -1) {
            list.push(id);
        } else {
            list.splice(idx, 1);
        }
        // Debounced reload instead of immediate
        this.scheduleReload();
    }

    // Select All matching the search query in the filter
    selectAllFiltered(dropdownKey, filterKey) {
        const filteredList = this.getFilteredList(dropdownKey);
        const selected = new Set(this.state.filters[filterKey] || []);
        filteredList.forEach(item => {
            selected.add(item.id);
        });
        this.state.filters[filterKey] = Array.from(selected);
        this.scheduleReload();
    }

    // Clear all selected items for a filter
    clearAll(filterKey) {
        this.state.filters[filterKey] = [];
        this.scheduleReload();
    }

    // Reset All Filters
    resetFilters() {
        const currentYear = new Date().getFullYear();
        this.state.filters = {
            company_ids: [this.companyService.currentCompany.id],
            warehouse_ids: [],
            date_from: `${currentYear}-01-01`,
            date_to: new Date().toISOString().slice(0, 10),
            category_ids: [],
            product_ids: [],
            partner_ids: [],
        };
        // Invalidate all cached report data
        Object.keys(this.state.data.reports).forEach(k => {
            this.state.data.reports[k] = null;
        });
        this.loadActiveReport();
    }

    // Export to Excel (uses legacy full-data endpoint)
    exportToExcel() {
        const filters = this.state.filters;
        const company_ids = filters.company_ids.join(',');
        const warehouse_ids = filters.warehouse_ids.join(',');
        const category_ids = filters.category_ids.join(',');
        const product_ids = filters.product_ids.join(',');
        const partner_ids = filters.partner_ids.join(',');

        const url = `/inventory_dashboard/export_xlsx?company_ids=${company_ids}&warehouse_ids=${warehouse_ids}&date_from=${filters.date_from}&date_to=${filters.date_to}&category_ids=${category_ids}&product_ids=${product_ids}&partner_ids=${partner_ids}`;
        window.location.href = url;
    }

    // Local search within rendered tables
    getFilteredReportData(reportName) {
        const list = this.state.data.reports[reportName] || [];
        const query = (this.state.searchQueries[reportName] || '').toLowerCase();
        if (!query) return list;

        return list.filter(item => {
            return Object.values(item).some(val =>
                String(val || '').toLowerCase().includes(query)
            );
        });
    }

    // Display labels for selected filters
    getSelectedLabel(name, placeholder) {
        const selectedIds = this.state.filters[name];
        if (!selectedIds.length) return placeholder;

        let items = [];
        if (name === 'company_ids') items = this.state.data.companies;
        else if (name === 'warehouse_ids') items = this.state.data.warehouses;
        else if (name === 'category_ids') items = this.state.data.categories;
        else if (name === 'product_ids') items = this.state.data.products;
        else if (name === 'partner_ids') items = this.state.data.partners;

        const names = items
            .filter(item => selectedIds.includes(item.id))
            .map(item => item.name);

        if (names.length === 0) return placeholder;
        if (names.length === 1) return names[0];
        return `${names.length} Selected`;
    }

    // ── Drill-down: open a native Odoo list view with a filtered domain ──────────
    openListView(model, domain, name, context) {
        this.actionService.doAction({
            type: 'ir.actions.act_window',
            name: name,
            res_model: model,
            views: [[false, 'list'], [false, 'form']],
            domain: domain,
            context: context || {},
            target: 'current',
        });
    }

    // Tab 1: Inventory Status — click row → stock.move list for that product
    drillInventoryStatus(item) {
        const f = this.state.filters;
        const dtFrom = f.date_from + ' 00:00:00';
        const dtTo   = f.date_to   + ' 23:59:59';
        this.openListView(
            'stock.move',
            [
                ['product_id', '=', item.product_id],
                ['state', '=', 'done'],
                ['date', '>=', dtFrom],
                ['date', '<=', dtTo],
            ],
            `Stock Moves — ${item.item_name || item.item_code}`,
            { search_default_done: 1 }
        );
    }

    // Receipt details — destination location is internal, source is not internal
    drillReceipts(item, ev) {
        if (ev && ev.stopPropagation) ev.stopPropagation();
        const f = this.state.filters;
        const dtFrom = f.date_from + ' 00:00:00';
        const dtTo   = f.date_to   + ' 23:59:59';
        this.openListView(
            'stock.move',
            [
                ['product_id', '=', item.product_id],
                ['state', '=', 'done'],
                ['date', '>=', dtFrom],
                ['date', '<=', dtTo],
                ['location_dest_id.usage', '=', 'internal'],
                ['location_id.usage', '!=', 'internal'],
            ],
            `Receipt Details — ${item.item_name || item.item_code}`
        );
    }

    // Issue history & locations — source location is internal, destination is not internal
    drillIssues(item, ev) {
        if (ev && ev.stopPropagation) ev.stopPropagation();
        const f = this.state.filters;
        const dtFrom = f.date_from + ' 00:00:00';
        const dtTo   = f.date_to   + ' 23:59:59';
        this.openListView(
            'stock.move',
            [
                ['product_id', '=', item.product_id],
                ['state', '=', 'done'],
                ['date', '>=', dtFrom],
                ['date', '<=', dtTo],
                ['location_id.usage', '=', 'internal'],
                ['location_dest_id.usage', '!=', 'internal'],
            ],
            `Stock Issues & Locations — ${item.item_name || item.item_code}`
        );
    }

    // Tab 2: Stock Ledger — click row → stock.move filtered by reference
    drillStockLedger(line) {
        const f = this.state.filters;
        const dtFrom = f.date_from + ' 00:00:00';
        const dtTo   = f.date_to   + ' 23:59:59';
        const domain = [
            ['product_id', '=', line.product_id],
            ['state', '=', 'done'],
            ['date', '>=', dtFrom],
            ['date', '<=', dtTo],
        ];
        if (line.reference && line.reference !== 'N/A') {
            domain.push(['reference', '=', line.reference]);
        }
        this.openListView(
            'stock.move',
            domain,
            `Stock Ledger — ${line.item_name || line.item_code}`
        );
    }

    // Tab 3: Ageing Analysis — click row → stock.quant for that product
    drillAgeingAnalysis(item) {
        this.openListView(
            'stock.quant',
            [
                ['product_id', '=', item.product_id],
                ['location_id.usage', '=', 'internal'],
                ['quantity', '>', 0],
            ],
            `Stock On Hand — ${item.item_name || item.item_code}`,
            { search_default_internal_loc: 1 }
        );
    }

    // Tab 4: Pending PO — click row → purchase.order.line filtered by product + vendor
    drillPendingPO(po) {
        const f = this.state.filters;
        const domain = [
            ['product_id', '=', po.product_id],
            ['order_id.state', 'in', ['purchase', 'done']],
            ['qty_to_invoice', '>', 0],
        ];
        if (po.partner_id) {
            domain.push(['order_id.partner_id', '=', po.partner_id]);
        }
        if (f.date_from) {
            domain.push(['order_id.date_order', '>=', f.date_from]);
        }
        if (f.date_to) {
            domain.push(['order_id.date_order', '<=', f.date_to + ' 23:59:59']);
        }
        this.openListView(
            'purchase.order.line',
            domain,
            `Pending PO Lines — ${po.item_description || po.item_code}`
        );
    }
}

registry.category("actions").add("ss_inventory_dashboard_tag", InventoryDashboard);
