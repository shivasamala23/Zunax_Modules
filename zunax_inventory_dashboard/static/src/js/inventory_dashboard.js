/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";
import { Layout } from "@web/search/layout";
import { _t } from "@web/core/l10n/translation";

export class ZunaxInventoryDashboard extends Component {
    static template = "zunax_inventory_dashboard.InventoryDashboard";
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
        
        // Load persisted filters from localStorage
        let savedFilters = {};
        try {
            const stored = localStorage.getItem("zunax_inventory_dashboard_filters");
            if (stored) {
                savedFilters = JSON.parse(stored);
            }
        } catch (e) {
            console.error("Failed to load saved filters:", e);
        }

        this.state = useState({
            loading: true,
            isRefreshing: false,
            filters: {
                company_ids: savedFilters.company_ids || [this.companyService.currentCompany.id],
                date_from: savedFilters.date_from || `${currentYear}-01-01`,
                date_to: savedFilters.date_to || new Date().toISOString().slice(0, 10),
                category_ids: savedFilters.category_ids || [],
                product_ids: savedFilters.product_ids || [],
                location_ids: savedFilters.location_ids || [],
            },
            dropdowns: {
                location: { isOpen: false, search: '' },
                category: { isOpen: false, search: '' },
                product: { isOpen: false, search: '' },
            },
            data: {
                categories: [],
                products: [],
                locations: [],
                kpis: {}
            }
        });

        onWillStart(async () => {
            await this.loadDashboardData(true);
        });
    }

    saveFilters() {
        try {
            localStorage.setItem("zunax_inventory_dashboard_filters", JSON.stringify(this.state.filters));
        } catch (e) {
            console.error("Failed to save filters to localStorage:", e);
        }
    }

    // Filter search text getters
    get filteredLocations() {
        const search = (this.state.dropdowns.location.search || '').toLowerCase();
        if (!search) return this.state.data.locations;
        return this.state.data.locations.filter(l => 
            (l.complete_name || l.name || '').toLowerCase().includes(search)
        );
    }

    get filteredCategories() {
        const search = (this.state.dropdowns.category.search || '').toLowerCase();
        if (!search) return this.state.data.categories;
        return this.state.data.categories.filter(c => 
            (c.name || '').toLowerCase().includes(search)
        );
    }

    get filteredProducts() {
        const search = (this.state.dropdowns.product.search || '').toLowerCase();
        if (!search) return this.state.data.products;
        return this.state.data.products.filter(p => 
            (p.name || '').toLowerCase().includes(search)
        );
    }

    onSearchInput(type, ev) {
        this.state.dropdowns[type].search = ev.target.value;
    }

    async loadDashboardData(isInitial = false) {
        if (isInitial) {
            this.state.loading = true;
        } else {
            this.state.isRefreshing = true;
        }
        try {
            const f = this.state.filters;
            const result = await this.orm.call(
                "zunax.inventory.dashboard",
                "get_dashboard_data",
                [],
                {
                    company_ids: f.company_ids,
                    date_from: f.date_from,
                    date_to: f.date_to,
                    category_ids: f.category_ids,
                    product_ids: f.product_ids,
                    location_ids: f.location_ids,
                }
            );

            if (result) {
                this.state.data.categories = result.categories || [];
                this.state.data.products = result.products || [];
                this.state.data.locations = result.locations || [];
                this.state.data.quant_view_id = result.quant_view_id || false;
                this.state.data.move_view_id = result.move_view_id || false;
                this.state.data.kpis = result.kpis || {};

                // Only sync company_ids from server; never overwrite user's filter selections
                if (result.filters && result.filters.company_ids) {
                    this.state.filters.company_ids = result.filters.company_ids;
                }
                this.saveFilters();
            }
        } catch (e) {
            console.error("Failed to load inventory dashboard data:", e);
        } finally {
            this.state.loading = false;
            this.state.isRefreshing = false;
        }
    }

    async refreshDashboard() {
        await this.loadDashboardData(false);
    }

    // ── Dropdown Controls ───────────────────────────────────────────────────
    toggleDropdown(type) {
        const isCurrentlyOpen = this.state.dropdowns[type].isOpen;
        // Close all dropdowns
        Object.keys(this.state.dropdowns).forEach(k => {
            this.state.dropdowns[k].isOpen = false;
            this.state.dropdowns[k].search = '';
        });
        // Toggle selected
        this.state.dropdowns[type].isOpen = !isCurrentlyOpen;
    }

    closeDropdowns() {
        Object.keys(this.state.dropdowns).forEach(k => {
            this.state.dropdowns[k].isOpen = false;
            this.state.dropdowns[k].search = '';
        });
    }

    // Filter label displays
    get selectedLocationsLabel() {
        const selected = this.state.data.locations.filter(l => this.state.filters.location_ids.includes(l.id));
        if (selected.length === 0) return "All Locations";
        if (selected.length === 1) return selected[0].complete_name || selected[0].name;
        return `${selected.length} Locations`;
    }

    get selectedCategoriesLabel() {
        const selected = this.state.data.categories.filter(c => this.state.filters.category_ids.includes(c.id));
        if (selected.length === 0) return "All Categories";
        if (selected.length === 1) return selected[0].name;
        return `${selected.length} Categories`;
    }

    get selectedProductsLabel() {
        const selected = this.state.data.products.filter(p => this.state.filters.product_ids.includes(p.id));
        if (selected.length === 0) return "All Products";
        if (selected.length === 1) return selected[0].name;
        return `${selected.length} Products`;
    }

    async toggleLocation(id) {
        const idx = this.state.filters.location_ids.indexOf(id);
        if (idx > -1) {
            this.state.filters.location_ids.splice(idx, 1);
        } else {
            this.state.filters.location_ids.push(id);
        }
        await this.loadDashboardData(false);
    }

    async toggleCategory(id) {
        const idx = this.state.filters.category_ids.indexOf(id);
        if (idx > -1) {
            this.state.filters.category_ids.splice(idx, 1);
        } else {
            this.state.filters.category_ids.push(id);
        }
        await this.loadDashboardData(false);
    }

    async toggleProduct(id) {
        const idx = this.state.filters.product_ids.indexOf(id);
        if (idx > -1) {
            this.state.filters.product_ids.splice(idx, 1);
        } else {
            this.state.filters.product_ids.push(id);
        }
        await this.loadDashboardData(false);
    }

    async selectAll(type) {
        if (type === 'location') {
            this.state.filters.location_ids = this.filteredLocations.map(l => l.id);
        } else if (type === 'category') {
            this.state.filters.category_ids = this.filteredCategories.map(c => c.id);
        } else if (type === 'product') {
            this.state.filters.product_ids = this.filteredProducts.map(p => p.id);
        }
        await this.loadDashboardData(false);
    }

    async unselectAll(type) {
        if (type === 'location') {
            this.state.filters.location_ids = [];
        } else if (type === 'category') {
            this.state.filters.category_ids = [];
        } else if (type === 'product') {
            this.state.filters.product_ids = [];
        }
        await this.loadDashboardData(false);
    }

    // ── Input/Date Handlers ─────────────────────────────────────────────────
    async onDateFromChange(ev) {
        this.state.filters.date_from = ev.target.value;
        await this.loadDashboardData(false);
    }

    async onDateToChange(ev) {
        this.state.filters.date_to = ev.target.value;
        await this.loadDashboardData(false);
    }

    async resetFilters() {
        const currentYear = new Date().getFullYear();
        this.state.filters = {
            company_ids: [this.companyService.currentCompany.id],
            date_from: `${currentYear}-01-01`,
            date_to: new Date().toISOString().slice(0, 10),
            category_ids: [],
            product_ids: [],
            location_ids: [],
        };
        await this.loadDashboardData(false);
    }

    // ── Format Helper ───────────────────────────────────────────────────────
    formatVal(val) {
        return (val || 0).toLocaleString('en-IN', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
    }

    formatValNoDecimal(val) {
        return (val || 0).toLocaleString('en-IN', {
            maximumFractionDigits: 0
        });
    }

    async openOpeningMoves() {
        const f = this.state.filters;
        const action = await this.orm.call(
            "zunax.inventory.dashboard",
            "action_open_opening_valuation",
            [],
            {
                company_ids: f.company_ids,
                date_from: f.date_from,
                category_ids: f.category_ids,
                product_ids: f.product_ids,
                location_ids: f.location_ids,
            }
        );
        if (action) {
            await this.actionService.doAction(action);
        }
    }

    async openReceiptMoves() {
        const domain = [
            ['state', '=', 'done'],
            ['date', '>=', this.state.filters.date_from + ' 00:00:00'],
            ['date', '<=', this.state.filters.date_to + ' 23:59:59'],
            ['picking_code', '=', 'incoming'],
        ];
        if (this.state.filters.location_ids && this.state.filters.location_ids.length > 0) {
            domain.push(['location_dest_id', 'in', this.state.filters.location_ids]);
            domain.push(['location_id', 'not in', this.state.filters.location_ids]);
        } else {
            domain.push(['location_dest_id.usage', '=', 'internal']);
            domain.push(['location_id.usage', '!=', 'internal']);
        }
        if (this.state.filters.product_ids && this.state.filters.product_ids.length > 0) {
            domain.push(['product_id', 'in', this.state.filters.product_ids]);
        }
        if (this.state.filters.category_ids && this.state.filters.category_ids.length > 0) {
            domain.push(['product_id.categ_id', 'child_of', this.state.filters.category_ids]);
        }
        if (this.state.filters.company_ids && this.state.filters.company_ids.length > 0) {
            domain.push(['company_id', 'in', this.state.filters.company_ids]);
        }
        const viewId = this.state.data.move_view_id || false;
        await this.actionService.doAction({
            name: _t("GRN / Receipts Stock Moves"),
            type: "ir.actions.act_window",
            res_model: "stock.move",
            views: [[viewId, "list"], [false, "form"]],
            domain: domain,
            target: "current"
        });
    }

    async openIssueMoves() {
        const domain = [
            ['state', '=', 'done'],
            ['date', '>=', this.state.filters.date_from + ' 00:00:00'],
            ['date', '<=', this.state.filters.date_to + ' 23:59:59'],
        ];
        if (this.state.filters.location_ids && this.state.filters.location_ids.length > 0) {
            domain.push(['location_id', 'in', this.state.filters.location_ids]);
            domain.push(['location_dest_id', 'not in', this.state.filters.location_ids]);
        } else {
            domain.push(['location_id.usage', '=', 'internal']);
            domain.push(['location_dest_id.usage', '!=', 'internal']);
        }
        if (this.state.filters.product_ids && this.state.filters.product_ids.length > 0) {
            domain.push(['product_id', 'in', this.state.filters.product_ids]);
        }
        if (this.state.filters.category_ids && this.state.filters.category_ids.length > 0) {
            domain.push(['product_id.categ_id', 'child_of', this.state.filters.category_ids]);
        }
        if (this.state.filters.company_ids && this.state.filters.company_ids.length > 0) {
            domain.push(['company_id', 'in', this.state.filters.company_ids]);
        }
        const viewId = this.state.data.move_view_id || false;
        await this.actionService.doAction({
            name: _t("Stock Issue Moves"),
            type: "ir.actions.act_window",
            res_model: "stock.move",
            views: [[viewId, "list"], [false, "form"]],
            domain: domain,
            target: "current"
        });
    }

    async openClosingStock() {
        const f = this.state.filters;
        const action = await this.orm.call(
            "zunax.inventory.dashboard",
            "action_open_closing_valuation",
            [],
            {
                company_ids: f.company_ids,
                date_to: f.date_to,
                category_ids: f.category_ids,
                product_ids: f.product_ids,
                location_ids: f.location_ids,
            }
        );
        if (action) {
            await this.actionService.doAction(action);
        }
    }

    async openAgedStock(daysMin, daysMax) {
        const f = this.state.filters;
        const action = await this.orm.call(
            "zunax.inventory.dashboard",
            "action_open_aged_stock",
            [],
            {
                days_min: daysMin,
                days_max: daysMax,
                company_ids: f.company_ids,
                date_to: f.date_to,
                category_ids: f.category_ids,
                product_ids: f.product_ids,
                location_ids: f.location_ids,
            }
        );
        if (action) {
            await this.actionService.doAction(action);
        }
    }
}

registry.category("actions").add("zunax_inventory_dashboard_tag", ZunaxInventoryDashboard);
