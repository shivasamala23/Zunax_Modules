/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState, useEffect } from "@odoo/owl";
import { Layout } from "@web/search/layout";
import { _t } from "@web/core/l10n/translation";
import { loadBundle } from "@web/core/assets";

export class PurchaseDashboard extends Component {
    static template = "ss_purchase_dashboard.PurchaseDashboard";
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

        // Load filters from sessionStorage if available
        const savedFilters = sessionStorage.getItem('purchase_dashboard_filters');
        let initialFilters = {
            year: '2026', // Set default year to 2026 to ensure data renders
            month: 'all',
            date_from: '',
            date_to: '',
            category_ids: [],
            partner_ids: [],
            exclude_partner_ids: [],
            exclude_branches: 'with', // 'with' or 'without'
        };
        if (savedFilters) {
            try {
                initialFilters = JSON.parse(savedFilters);
            } catch (e) {
                console.error("Failed to parse saved filters:", e);
            }
        }

        // Load Price Tendency filters from sessionStorage if available
        const savedPtFilters = sessionStorage.getItem('purchase_dashboard_pt_filters');
        let initialPtFilters = {
            granularity: 'month',
            productSearchQuery: '',
            categorySearchQuery: '',
            productNameSearch: '',
            selectedProductIds: [],
            selectedCategoryIds: [],
            data: null,
            loading: false,
        };
        if (savedPtFilters) {
            try {
                const parsedPt = JSON.parse(savedPtFilters);
                initialPtFilters = { ...initialPtFilters, ...parsedPt };
            } catch (e) {
                console.error("Failed to parse saved Price Tendency filters:", e);
            }
        }

        // Load Aging Report filters from sessionStorage if available
        const savedAgingFilters = sessionStorage.getItem('purchase_dashboard_aging_filters');
        let initialAgingFilters = {
            loading: false,
            vendors: [],
            summary: {},
            allVendors: [],
            vendorSearch: '',
            selectedVendorIds: [],
            dropdownOpen: false,
        };
        if (savedAgingFilters) {
            try {
                const parsedAging = JSON.parse(savedAgingFilters);
                initialAgingFilters = { ...initialAgingFilters, ...parsedAging };
            } catch (e) {
                console.error("Failed to parse saved Aging Report filters:", e);
            }
        }

        // Load Price Comparison filters from sessionStorage if available
        const savedPcFilters = sessionStorage.getItem('purchase_dashboard_pc_filters');
        let initialPcFilters = {
            selectedCategoryId: null,
            selectedCategoryName: 'Select Category',
            selectedProductIds: [],
            categorySearchQuery: '',
            productSearchQuery: '',
            products: [],
            vendors: [],
            rows: [],
            loading: false,
            categoryDropdownOpen: false,
            productDropdownOpen: false,
        };
        if (savedPcFilters) {
            try {
                const parsedPc = JSON.parse(savedPcFilters);
                initialPcFilters = { ...initialPcFilters, ...parsedPc };
            } catch (e) {
                console.error("Failed to parse saved Price Comparison filters:", e);
            }
        }

        // Reactively manage state of dashboard data and filters
        this.state = useState({
            data: {},
            loading: true,
            filters: initialFilters,
            activeDropdown: null,
            categorySearchQuery: '',
            vendorSearchQuery: '',
            excludeVendorSearchQuery: '',
            // Price Tendency
            priceTendency: initialPtFilters,
            priceTendencyProductDropdownOpen: false,
            priceTendencyCategoryDropdownOpen: false,
            purchasableProducts: [],
            // Aging Report
            agingReport: initialAgingFilters,
            // Price Comparison
            priceComparison: initialPcFilters,
        });

        this.onYearChange = this.onYearChange.bind(this);
        this.onMonthChange = this.onMonthChange.bind(this);
        this.onDateFromChange = this.onDateFromChange.bind(this);
        this.onDateToChange = this.onDateToChange.bind(this);
        this.onCategoryToggle = this.onCategoryToggle.bind(this);
        this.resetFilters = this.resetFilters.bind(this);
        this.refreshDashboard = this.refreshDashboard.bind(this);
        this.openModelList = this.openModelList.bind(this);
        this.onPOStatusClick = this.onPOStatusClick.bind(this);
        this.onRFQStatusClick = this.onRFQStatusClick.bind(this);
        this.onCategorySearchInput = this.onCategorySearchInput.bind(this);
        this.selectAllCategories = this.selectAllCategories.bind(this);
        this.clearAllCategories = this.clearAllCategories.bind(this);
        this.exportToExcel = this.exportToExcel.bind(this);
        this.toggleCategoryDropdown = this.toggleCategoryDropdown.bind(this);
        this.toggleVendorDropdown = this.toggleVendorDropdown.bind(this);
        this.onVendorSearchInput = this.onVendorSearchInput.bind(this);
        this.selectAllVendors = this.selectAllVendors.bind(this);
        this.clearAllVendors = this.clearAllVendors.bind(this);
        this.onVendorToggle = this.onVendorToggle.bind(this);
        this.toggleExcludeVendorDropdown = this.toggleExcludeVendorDropdown.bind(this);
        this.onExcludeVendorSearchInput = this.onExcludeVendorSearchInput.bind(this);
        this.selectAllExcludeVendors = this.selectAllExcludeVendors.bind(this);
        this.clearAllExcludeVendors = this.clearAllExcludeVendors.bind(this);
        this.onExcludeVendorToggle = this.onExcludeVendorToggle.bind(this);
        this.openPendingPOLines = this.openPendingPOLines.bind(this);
        this.onPriceTendencyGranularityChange = this.onPriceTendencyGranularityChange.bind(this);
        this.onPriceTendencyProductSearch = this.onPriceTendencyProductSearch.bind(this);
        this.togglePriceTendencyProductDropdown = this.togglePriceTendencyProductDropdown.bind(this);
        this.onPriceTendencyProductToggle = this.onPriceTendencyProductToggle.bind(this);
        this.clearPriceTendencyProducts = this.clearPriceTendencyProducts.bind(this);
        this.togglePriceTendencyCategoryDropdown = this.togglePriceTendencyCategoryDropdown.bind(this);
        this.onPriceTendencyCategoryToggle = this.onPriceTendencyCategoryToggle.bind(this);
        this.clearPriceTendencyCategories = this.clearPriceTendencyCategories.bind(this);
        this.clearPriceTendencyFilters = this.clearPriceTendencyFilters.bind(this);
        this.onPriceTendencyProductNameInput = this.onPriceTendencyProductNameInput.bind(this);
        this.onPriceTendencyProductSearchInput = this.onPriceTendencyProductSearchInput.bind(this);
        this.onPriceTendencyCategorySearchInput = this.onPriceTendencyCategorySearchInput.bind(this);
        this.onExcludeBranchesChange = this.onExcludeBranchesChange.bind(this);
        this.openPriceTendencyDetail = this.openPriceTendencyDetail.bind(this);
        this.openDelayedDeliveries = this.openDelayedDeliveries.bind(this);
        this.loadAgingReport = this.loadAgingReport.bind(this);
        this.onAgingVendorSearchInput = this.onAgingVendorSearchInput.bind(this);
        this.onAgingVendorToggle = this.onAgingVendorToggle.bind(this);
        this.toggleAgingVendorDropdown = this.toggleAgingVendorDropdown.bind(this);
        this.clearAgingVendors = this.clearAgingVendors.bind(this);
        this.openSavingsReport = this.openSavingsReport.bind(this);
        this.openAgingVendorBills = this.openAgingVendorBills.bind(this);
        this.openCriticalSuppliers = this.openCriticalSuppliers.bind(this);

        // Price Comparison
        this.togglePcCategoryDropdown = this.togglePcCategoryDropdown.bind(this);
        this.onPcCategorySearchInput = this.onPcCategorySearchInput.bind(this);
        this.selectPcCategory = this.selectPcCategory.bind(this);
        this.togglePcProductDropdown = this.togglePcProductDropdown.bind(this);
        this.onPcProductSearchInput = this.onPcProductSearchInput.bind(this);
        this.onPcProductToggle = this.onPcProductToggle.bind(this);
        this.clearPcProducts = this.clearPcProducts.bind(this);
        this.loadPcProducts = this.loadPcProducts.bind(this);
        this.loadPriceComparison = this.loadPriceComparison.bind(this);
        this.exportPcToExcel = this.exportPcToExcel.bind(this);
        this.openPcBills = this.openPcBills.bind(this);
        this.openPcPos = this.openPcPos.bind(this);
        this.openPcBestPrice = this.openPcBestPrice.bind(this);

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.loadDashboardData();
            // load purchasable products list for the filter dropdown
            await this.loadPurchasableProducts();
            await this.loadPriceTendency();
            if (this.state.priceComparison.selectedCategoryId) {
                await this.loadPcProducts();
            }
            await this.loadPriceComparison();
            await this.loadAgingReport();
        });

        // Main Dashboard Charts Effect
        useEffect(() => {
            if (!this.state.loading && this.state.data.kpis) {
                this.renderCharts();
            }
            return () => {
                if (this.spendChart) {
                    this.spendChart.destroy();
                    this.spendChart = null;
                }
                if (this.agingChart) {
                    this.agingChart.destroy();
                    this.agingChart = null;
                }
            };
        }, () => [this.state.loading, this.state.data]);

        // Price Tendency Chart Effect
        useEffect(() => {
            if (!this.state.priceTendency.loading && this.state.priceTendency.data) {
                this.renderPriceTendencyChart();
            }
            return () => {
                if (this.priceTendencyChart) {
                    this.priceTendencyChart.destroy();
                    this.priceTendencyChart = null;
                }
            };
        }, () => [this.state.priceTendency.loading, this.state.priceTendency.data]);
    }

    async loadDashboardData() {
        try {
            sessionStorage.setItem('purchase_dashboard_filters', JSON.stringify(this.state.filters));
            this.state.loading = true;
            const currentCompanyId = this.companyService.currentCompany.id;
            // Collect ALL active company IDs from the Odoo company switcher
            const activeCompanyIds = (this.companyService.activeCompanyIds || [currentCompanyId]).map(id => parseInt(id));
            const res = await this.orm.call(
                "purchase.dashboard",
                "get_dashboard_data",
                [],
                {
                    company_id: currentCompanyId,
                    company_ids: activeCompanyIds,
                    year: this.state.filters.year,
                    month: this.state.filters.month,
                    date_from: this.state.filters.date_from || null,
                    date_to: this.state.filters.date_to || null,
                    category_ids: this.state.filters.category_ids,
                    partner_ids: this.state.filters.partner_ids,
                    exclude_partner_ids: this.state.filters.exclude_partner_ids,
                    exclude_branches: this.state.filters.exclude_branches === 'without',
                }
            );
            this.state.data = res;
            this.state.loading = false;
        } catch (e) {
            console.error("Error loading purchase dashboard data:", e);
            // Always set loading=false so the page renders, even if empty
            this.state.loading = false;
            // Set safe defaults so template doesn't crash
            this.state.data = {
                kpis: { pr_pending: 0, rfq_pending: 0, po_pending: 0, open_po_value: 0, outstanding_amount: 0, packing_material_pending: 0, delayed_deliveries: 0, critical_suppliers: 0 },
                pr_status: { breakdown: [], metrics: {} },
                rfq_status: { breakdown: [], metrics: {} },
                po_status: { breakdown: [], metrics: {} },
                liabilities: { open_po_val: 0, grn_pending_val: 0, invoice_pending_val: 0, outstanding_amount: 0, aging_analysis: [] },
                category_spend: { breakdown: [], total_spend: 0 },
                category_pending_pos: { list: [], kpis: {} },
                vendor_performance: { list: [], kpis: {} },
                material_risk: { list: [], indicators: {} },
                spend_analysis: { chart_data: [], kpis: {} },
                product_categories: [],
                _error: true,
            };
        }
    }

    async refreshDashboard() {
        await this.loadDashboardData();
        await this.loadAgingReport();
        if (this.state.priceComparison.selectedCategoryId) {
            await this.loadPriceComparison();
        }
    }

    async loadAgingReport() {
        try {
            const ar = this.state.agingReport;
            sessionStorage.setItem('purchase_dashboard_aging_filters', JSON.stringify({
                selectedVendorIds: ar.selectedVendorIds,
                vendorSearch: ar.vendorSearch,
            }));
            this.state.agingReport.loading = true;
            const currentCompanyId = this.companyService.currentCompany.id;
            const activeCompanyIds = (this.companyService.activeCompanyIds || [currentCompanyId]).map(id => parseInt(id));
            const res = await this.orm.call(
                'purchase.dashboard',
                'get_aging_report',
                [],
                {
                    company_id: currentCompanyId,
                    company_ids: activeCompanyIds,
                    exclude_branches: this.state.filters.exclude_branches === 'without',
                    vendor_search: this.state.agingReport.vendorSearch || '',
                    vendor_ids: this.state.agingReport.selectedVendorIds.length > 0
                        ? this.state.agingReport.selectedVendorIds : null,
                }
            );
            this.state.agingReport.vendors = res.vendors || [];
            this.state.agingReport.summary = res.summary || {};
            this.state.agingReport.allVendors = res.all_vendors || [];
            this.state.agingReport.loading = false;
        } catch (e) {
            console.error('Error loading aging report:', e);
            this.state.agingReport.loading = false;
            this.state.agingReport.vendors = [];
        }
    }

    toggleAgingVendorDropdown() {
        this.state.agingReport.dropdownOpen = !this.state.agingReport.dropdownOpen;
        if (this.state.agingReport.dropdownOpen) {
            this.state.activeDropdown = 'aging_vendor';
        } else {
            this.state.activeDropdown = null;
        }
    }

    onAgingVendorSearchInput(ev) {
        this.state.agingReport.vendorSearch = ev.target.value;
    }

    async onAgingVendorToggle(vendorId) {
        const ids = [...this.state.agingReport.selectedVendorIds];
        const idx = ids.indexOf(vendorId);
        if (idx >= 0) {
            ids.splice(idx, 1);
        } else {
            ids.push(vendorId);
        }
        this.state.agingReport.selectedVendorIds = ids;
        await this.loadAgingReport();
    }

    async clearAgingVendors() {
        this.state.agingReport.selectedVendorIds = [];
        this.state.agingReport.vendorSearch = '';
        await this.loadAgingReport();
    }

    // Open bills for a specific vendor from the aging table
    openAgingVendorBills(partnerId, bucket) {
        const domain = [
            ['move_type', '=', 'in_invoice'],
            ['state', '=', 'posted'],
            ['payment_state', '!=', 'paid'],
            ['partner_id', '=', partnerId],
        ];
        if (this.state.data.company_ids && this.state.data.company_ids.length > 0) {
            domain.push(['company_id', 'in', this.state.data.company_ids]);
        }
        // Add date_maturity filter per bucket
        const today = new Date().toISOString().split('T')[0];
        const d30 = new Date(Date.now() - 30 * 86400000).toISOString().split('T')[0];
        const d60 = new Date(Date.now() - 60 * 86400000).toISOString().split('T')[0];
        const d90 = new Date(Date.now() - 90 * 86400000).toISOString().split('T')[0];
        if (bucket === '0-30') {
            domain.push(['invoice_date_due', '>=', d30]);
            domain.push(['invoice_date_due', '<', today]);
        } else if (bucket === '31-60') {
            domain.push(['invoice_date_due', '>=', d60]);
            domain.push(['invoice_date_due', '<', d30]);
        } else if (bucket === '61-90') {
            domain.push(['invoice_date_due', '>=', d90]);
            domain.push(['invoice_date_due', '<', d60]);
        } else if (bucket === '90+') {
            domain.push(['invoice_date_due', '<', d90]);
        }
        this.actionService.doAction({
            type: 'ir.actions.act_window',
            name: `Aging Bills — ${bucket} Days`,
            res_model: 'account.move',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: domain,
            target: 'current',
            context: { default_move_type: 'in_invoice' },
        });
    }

    async onYearChange(ev) {
        this.state.filters.year = ev.target.value;
        if (ev.target.value !== 'all') {
            this.state.filters.date_from = '';
            this.state.filters.date_to = '';
        }
        await this.refreshDashboard();
    }

    async onMonthChange(ev) {
        this.state.filters.month = ev.target.value;
        if (ev.target.value !== 'all') {
            this.state.filters.date_from = '';
            this.state.filters.date_to = '';
        }
        await this.refreshDashboard();
    }

    async onDateFromChange(ev) {
        this.state.filters.date_from = ev.target.value;
        if (ev.target.value) {
            this.state.filters.year = 'all';
            this.state.filters.month = 'all';
        }
        await this.refreshDashboard();
    }

    async onDateToChange(ev) {
        this.state.filters.date_to = ev.target.value;
        if (ev.target.value) {
            this.state.filters.year = 'all';
            this.state.filters.month = 'all';
        }
        await this.refreshDashboard();
    }

    toggleCategoryDropdown(dropdownName) {
        if (this.state.activeDropdown === dropdownName) {
            this.state.activeDropdown = null;
        } else {
            this.state.activeDropdown = dropdownName;
            this.state.categorySearchQuery = '';
        }
    }

    onCategorySearchInput(ev) {
        this.state.categorySearchQuery = ev.target.value;
    }

    get filteredCategories() {
        if (!this.state.data.product_categories) return [];
        const query = (this.state.categorySearchQuery || '').toLowerCase().trim();
        if (!query) return this.state.data.product_categories;
        return this.state.data.product_categories.filter(cat =>
            (cat.name || '').toLowerCase().includes(query) ||
            (cat.complete_name || '').toLowerCase().includes(query)
        );
    }

    async selectAllCategories() {
        const visible = this.filteredCategories;
        const ids = [...this.state.filters.category_ids];
        for (const cat of visible) {
            if (!ids.includes(cat.id)) {
                ids.push(cat.id);
            }
        }
        this.state.filters.category_ids = ids;
        await this.refreshDashboard();
    }

    async clearAllCategories() {
        const visible = this.filteredCategories;
        const visibleIds = visible.map(c => c.id);
        this.state.filters.category_ids = this.state.filters.category_ids.filter(id => !visibleIds.includes(id));
        await this.refreshDashboard();
    }

    async onCategoryToggle(catId) {
        const ids = [...this.state.filters.category_ids];
        const index = ids.indexOf(catId);
        if (index > -1) {
            ids.splice(index, 1);
        } else {
            ids.push(catId);
        }
        this.state.filters.category_ids = ids;
        await this.refreshDashboard();
    }

    isCategorySelected(catId) {
        return this.state.filters.category_ids.includes(catId);
    }

    get selectedCategoriesLabel() {
        if (!this.state.data.product_categories) return "All Categories";
        const count = this.state.filters.category_ids.length;
        if (count === 0) return "All Categories";
        if (count === 1) {
            const cat = this.state.data.product_categories.find(c => c.id === this.state.filters.category_ids[0]);
            return cat ? cat.name : "1 Category";
        }
        return `${count} Categories Selected`;
    }

    get filteredAgingVendors() {
        const query = (this.state.agingReport.vendorSearch || '').toLowerCase().trim();
        if (!query) return this.state.agingReport.allVendors || [];
        return (this.state.agingReport.allVendors || []).filter(v =>
            (v.name || '').toLowerCase().includes(query)
        );
    }

    get selectedAgingVendorsLabel() {
        if (!this.state.agingReport.allVendors) return "All Vendors";
        const count = this.state.agingReport.selectedVendorIds.length;
        if (count === 0) return "All Vendors";
        if (count === 1) {
            const vendor = this.state.agingReport.allVendors.find(v => v.id === this.state.agingReport.selectedVendorIds[0]);
            return vendor ? vendor.name : "1 Vendor";
        }
        return `${count} Vendors Selected`;
    }

    isAgingVendorSelected(vendorId) {
        return this.state.agingReport.selectedVendorIds.includes(vendorId);
    }

    async resetFilters() {
        this.state.filters.year = 'all';
        this.state.filters.month = 'all';
        this.state.filters.date_from = '';
        this.state.filters.date_to = '';
        this.state.filters.category_ids = [];
        this.state.filters.partner_ids = [];
        this.state.filters.exclude_partner_ids = [];
        this.state.showCategoryDropdown = false;
        await this.refreshDashboard();
        await this.loadPriceTendency();
    }

    toggleExcludeVendorDropdown() {
        if (this.state.activeDropdown === 'exclude_vendors') {
            this.state.activeDropdown = null;
        } else {
            this.state.activeDropdown = 'exclude_vendors';
            this.state.excludeVendorSearchQuery = '';
        }
    }

    onExcludeVendorSearchInput(ev) {
        this.state.excludeVendorSearchQuery = ev.target.value;
    }

    get filteredExcludeVendors() {
        if (!this.state.data.vendors) return [];
        const query = (this.state.excludeVendorSearchQuery || '').toLowerCase().trim();
        if (!query) return this.state.data.vendors;
        return this.state.data.vendors.filter(v =>
            (v.name || '').toLowerCase().includes(query)
        );
    }

    async selectAllExcludeVendors() {
        const visible = this.filteredExcludeVendors;
        const ids = [...this.state.filters.exclude_partner_ids];
        for (const v of visible) {
            if (!ids.includes(v.id)) {
                ids.push(v.id);
            }
        }
        this.state.filters.exclude_partner_ids = ids;
        await this.refreshDashboard();
    }

    async clearAllExcludeVendors() {
        const visible = this.filteredExcludeVendors;
        const visibleIds = visible.map(v => v.id);
        this.state.filters.exclude_partner_ids = this.state.filters.exclude_partner_ids.filter(id => !visibleIds.includes(id));
        await this.refreshDashboard();
    }

    async onExcludeVendorToggle(partnerId) {
        const ids = [...this.state.filters.exclude_partner_ids];
        const index = ids.indexOf(partnerId);
        if (index > -1) {
            ids.splice(index, 1);
        } else {
            ids.push(partnerId);
        }
        this.state.filters.exclude_partner_ids = ids;
        await this.refreshDashboard();
    }

    isExcludeVendorSelected(partnerId) {
        return this.state.filters.exclude_partner_ids.includes(partnerId);
    }

    get excludeVendorsLabel() {
        if (!this.state.data.vendors) return "None Excluded";
        const count = this.state.filters.exclude_partner_ids.length;
        if (count === 0) return "None Excluded";
        if (count === 1) {
            const v = this.state.data.vendors.find(c => c.id === this.state.filters.exclude_partner_ids[0]);
            return v ? `Excluded: ${v.name}` : "1 Excluded";
        }
        return `${count} Excluded`;
    }

    toggleVendorDropdown() {
        if (this.state.activeDropdown === 'vendor_performance') {
            this.state.activeDropdown = null;
        } else {
            this.state.activeDropdown = 'vendor_performance';
            this.state.vendorSearchQuery = '';
        }
    }

    onVendorSearchInput(ev) {
        this.state.vendorSearchQuery = ev.target.value;
    }

    get filteredVendors() {
        if (!this.state.data.vendors) return [];
        const query = (this.state.vendorSearchQuery || '').toLowerCase().trim();
        if (!query) return this.state.data.vendors;
        return this.state.data.vendors.filter(v =>
            (v.name || '').toLowerCase().includes(query)
        );
    }

    async selectAllVendors() {
        const visible = this.filteredVendors;
        const ids = [...this.state.filters.partner_ids];
        for (const v of visible) {
            if (!ids.includes(v.id)) {
                ids.push(v.id);
            }
        }
        this.state.filters.partner_ids = ids;
        await this.refreshDashboard();
    }

    async clearAllVendors() {
        const visible = this.filteredVendors;
        const visibleIds = visible.map(v => v.id);
        this.state.filters.partner_ids = this.state.filters.partner_ids.filter(id => !visibleIds.includes(id));
        await this.refreshDashboard();
    }

    async onVendorToggle(partnerId) {
        const ids = [...this.state.filters.partner_ids];
        const index = ids.indexOf(partnerId);
        if (index > -1) {
            ids.splice(index, 1);
        } else {
            ids.push(partnerId);
        }
        this.state.filters.partner_ids = ids;
        await this.refreshDashboard();
    }

    isVendorSelected(partnerId) {
        return this.state.filters.partner_ids.includes(partnerId);
    }

    get selectedVendorsLabel() {
        if (!this.state.data.vendors) return "All Vendors";
        const count = this.state.filters.partner_ids.length;
        if (count === 0) return "All Vendors";
        if (count === 1) {
            const v = this.state.data.vendors.find(c => c.id === this.state.filters.partner_ids[0]);
            return v ? v.name : "1 Vendor";
        }
        return `${count} Vendors Selected`;
    }

    renderCharts() {
        // Destroy existing chart canvases if they have instances associated
        if (this.spendChart) {
            this.spendChart.destroy();
        }
        if (this.agingChart) {
            this.agingChart.destroy();
        }

        const spendCtx = document.getElementById("spendChartCanvas");
        const agingCtx = document.getElementById("agingChartCanvas");

        if (spendCtx && window.Chart && this.state.data.spend_analysis) {
            const chartData = this.state.data.spend_analysis.chart_data;
            const labels = chartData.map(d => d.month);
            const spendVals = chartData.map(d => d.spend);
            const savingVals = chartData.map(d => d.saving);

            this.spendChart = new window.Chart(spendCtx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [
                        {
                            label: 'Spend (₹)',
                            data: spendVals,
                            backgroundColor: 'rgba(79, 70, 229, 0.75)',
                            borderColor: '#4f46e5',
                            borderWidth: 1,
                            order: 2
                        },
                        {
                            label: 'Savings Achieved (₹)',
                            data: savingVals,
                            type: 'line',
                            borderColor: '#10b981',
                            backgroundColor: 'rgba(16, 185, 129, 0.1)',
                            fill: true,
                            tension: 0.3,
                            borderWidth: 2,
                            order: 1
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    onHover: (evt, activeElements) => {
                        evt.native.target.style.cursor = activeElements.length ? 'pointer' : 'default';
                    },
                    onClick: (evt, activeElements) => {
                        if (!activeElements || activeElements.length === 0) return;
                        const element = activeElements[0];
                        const datasetIndex = element.datasetIndex;
                        const labelIndex = element.index;
                        const clickedLabel = labels[labelIndex]; // e.g. "Jan" or "1" (day)
                        const monthsMap = {
                            'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04',
                            'May': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08',
                            'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'
                        };
                        const filters = this.state.filters;
                        const yearVal = (filters.year && filters.year !== 'all') ? filters.year : new Date().getFullYear();

                        let dateFrom, dateTo;
                        if (monthsMap[clickedLabel]) {
                            // Monthly view — label is a short month name like "Jan"
                            const m = monthsMap[clickedLabel];
                            const daysInMonth = new Date(parseInt(yearVal), parseInt(m), 0).getDate();
                            dateFrom = `${yearVal}-${m}-01`;
                            dateTo = `${yearVal}-${m}-${String(daysInMonth).padStart(2, '0')}`;
                        } else {
                            // Daily view (when a specific month is selected) — label is a day number
                            const dayNum = String(parseInt(clickedLabel)).padStart(2, '0');
                            const monthFilter = filters.month;
                            const m = monthsMap[monthFilter] || '01';
                            dateFrom = `${yearVal}-${m}-${dayNum}`;
                            dateTo = dateFrom;
                        }

                        if (datasetIndex === 1) {
                            // Clicked on Savings dataset
                            this.openSavingsReport(dateFrom, dateTo);
                        } else {
                            // Clicked on Spend dataset
                            const domain = [
                                ['move_type', '=', 'in_invoice'],
                                ['state', '=', 'posted'],
                                ['invoice_date', '>=', dateFrom],
                                ['invoice_date', '<=', dateTo],
                            ];
                            this.openModelList('account.move', domain, {
                                useDateFilter: false,
                                useCategoryFilter: true,
                                categoryField: 'invoice_line_ids.product_id.categ_id',
                                name: `Procurement Spend — ${clickedLabel} ${yearVal}`,
                                context: { default_move_type: 'in_invoice' }
                            });
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                callback: function (value) {
                                    return '₹' + (value >= 10000000 ? (value / 10000000).toFixed(1) + ' Cr' :
                                        (value >= 100000 ? (value / 100000).toFixed(1) + ' L' : value));
                                }
                            }
                        }
                    }
                }
            });
        }


        if (agingCtx && window.Chart && this.state.data.liabilities) {
            const agingData = this.state.data.liabilities.aging_analysis;
            const labels = agingData.map(d => d.bucket);
            const vals = agingData.map(d => d.amount);

            this.agingChart = new window.Chart(agingCtx, {
                type: 'doughnut',
                data: {
                    labels: labels,
                    datasets: [{
                        data: vals,
                        backgroundColor: [
                            'rgba(16, 185, 129, 0.8)', // 0-30
                            'rgba(14, 165, 233, 0.8)', // 31-60
                            'rgba(245, 158, 11, 0.8)', // 61-90
                            'rgba(239, 68, 68, 0.8)'   // 90+
                        ],
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'right'
                        }
                    }
                }
            });
        }
    }

    // ---------- Price Tendency Methods ----------

    async loadPurchasableProducts(search = '') {
        try {
            const companyId = this.companyService.currentCompany.id;
            const activeCompanyIds = (this.companyService.activeCompanyIds || [companyId]).map(id => parseInt(id));
            const products = await this.orm.call(
                'purchase.dashboard',
                'get_purchasable_products',
                [],
                {
                    company_id: companyId,
                    company_ids: activeCompanyIds,
                    search,
                    exclude_branches: this.state.filters.exclude_branches === 'without',
                }
            );
            this.state.purchasableProducts = products;
        } catch (e) {
            console.error('Error loading purchasable products:', e);
        }
    }

    async loadPriceTendency() {
        try {
            const pt = this.state.priceTendency;
            sessionStorage.setItem('purchase_dashboard_pt_filters', JSON.stringify({
                granularity: pt.granularity,
                productNameSearch: pt.productNameSearch,
                selectedProductIds: pt.selectedProductIds,
                selectedCategoryIds: pt.selectedCategoryIds,
            }));
            this.state.priceTendency.loading = true;
            const companyId = this.companyService.currentCompany.id;
            const activeCompanyIds = (this.companyService.activeCompanyIds || [companyId]).map(id => parseInt(id));
            const res = await this.orm.call(
                'purchase.dashboard',
                'get_price_tendency',
                [],
                {
                    company_id: companyId,
                    company_ids: activeCompanyIds,
                    granularity: pt.granularity,
                    // Always use 'all' for price tendency so it shows last 12 months
                    // regardless of the global year filter
                    year: 'all',
                    product_ids: pt.selectedProductIds,
                    category_ids: pt.selectedCategoryIds,
                    product_name: pt.productNameSearch || null,
                    exclude_branches: this.state.filters.exclude_branches === 'without',
                }
            );
            this.state.priceTendency.data = res;
            this.state.priceTendency.loading = false;
            // NOTE: Chart rendering is handled by useEffect after OWL DOM flush.
            // Do NOT call renderPriceTendencyChart() directly here.
        } catch (e) {
            console.error('Error loading price tendency:', e);
            this.state.priceTendency.loading = false;
        }
    }

    async onPriceTendencyGranularityChange(ev) {
        this.state.priceTendency.granularity = ev.target.value;
        await this.loadPriceTendency();
    }

    // Product name text search (debounced via timeout)
    onPriceTendencyProductNameInput(ev) {
        this.state.priceTendency.productNameSearch = ev.target.value;
        // Debounce: clear existing and set new 400ms delay
        if (this._productNameSearchTimer) clearTimeout(this._productNameSearchTimer);
        this._productNameSearchTimer = setTimeout(async () => {
            await this.loadPriceTendency();
        }, 400);
    }

    onPriceTendencyProductSearch(ev) {
        this.state.priceTendency.productSearchQuery = ev.target.value;
    }

    async onPriceTendencyProductSearchInput(ev) {
        const q = ev.target.value;
        this.state.priceTendency.productSearchQuery = q;
        if (this._ptProductSearchTimer) clearTimeout(this._ptProductSearchTimer);
        this._ptProductSearchTimer = setTimeout(() => this.loadPurchasableProducts(q), 300);
    }

    togglePriceTendencyProductDropdown() {
        this.state.priceTendencyProductDropdownOpen = !this.state.priceTendencyProductDropdownOpen;
        this.state.priceTendencyCategoryDropdownOpen = false;
    }

    async onPriceTendencyProductToggle(productId) {
        const ids = [...this.state.priceTendency.selectedProductIds];
        const idx = ids.indexOf(productId);
        if (idx > -1) {
            ids.splice(idx, 1);
        } else {
            ids.push(productId);
        }
        this.state.priceTendency.selectedProductIds = ids;
        this.state.priceTendency.selectedCategoryIds = [];
        await this.loadPriceTendency();
    }

    async clearPriceTendencyProducts() {
        this.state.priceTendency.selectedProductIds = [];
        this.state.priceTendencyProductDropdownOpen = false;
        await this.loadPriceTendency();
    }

    togglePriceTendencyCategoryDropdown() {
        this.state.priceTendencyCategoryDropdownOpen = !this.state.priceTendencyCategoryDropdownOpen;
        this.state.priceTendencyProductDropdownOpen = false;
        this.state.priceTendency.categorySearchQuery = '';
    }

    async onPriceTendencyCategoryToggle(catId) {
        const ids = [...this.state.priceTendency.selectedCategoryIds];
        const idx = ids.indexOf(catId);
        if (idx > -1) {
            ids.splice(idx, 1);
        } else {
            ids.push(catId);
        }
        this.state.priceTendency.selectedCategoryIds = ids;
        this.state.priceTendency.selectedProductIds = [];
        await this.loadPriceTendency();
    }

    async clearPriceTendencyCategories() {
        this.state.priceTendency.selectedCategoryIds = [];
        this.state.priceTendencyCategoryDropdownOpen = false;
        this.state.priceTendency.categorySearchQuery = '';
        await this.loadPriceTendency();
    }

    async clearPriceTendencyFilters() {
        this.state.priceTendency.selectedProductIds = [];
        this.state.priceTendency.selectedCategoryIds = [];
        this.state.priceTendency.productNameSearch = '';
        this.state.priceTendency.categorySearchQuery = '';
        this.state.priceTendency.productSearchQuery = '';
        this.state.priceTendencyProductDropdownOpen = false;
        this.state.priceTendencyCategoryDropdownOpen = false;
        await this.loadPriceTendency();
    }

    onPriceTendencyCategorySearchInput(ev) {
        this.state.priceTendency.categorySearchQuery = ev.target.value;
    }

    get filteredPriceTendencyCategories() {
        const categories = this.state.data.product_categories || [];
        const query = (this.state.priceTendency.categorySearchQuery || '').toLowerCase().trim();
        if (!query) return categories;
        return categories.filter(c => (c.name || '').toLowerCase().includes(query));
    }

    get filteredPriceTendencyProducts() {
        const products = this.state.purchasableProducts || [];
        const query = (this.state.priceTendency.productSearchQuery || '').toLowerCase().trim();
        if (!query) return products;
        return products.filter(p => (p.name || '').toLowerCase().includes(query));
    }

    isPriceTendencyProductSelected(productId) {
        return this.state.priceTendency.selectedProductIds.includes(productId);
    }

    isPriceTendencyCategorySelected(catId) {
        return this.state.priceTendency.selectedCategoryIds.includes(catId);
    }

    get priceTendencyProductLabel() {
        const count = this.state.priceTendency.selectedProductIds.length;
        if (count === 0) return 'All Products';
        return `${count} Product${count > 1 ? 's' : ''} Selected`;
    }

    get priceTendencyCategoryLabel() {
        const count = this.state.priceTendency.selectedCategoryIds.length;
        if (count === 0) return 'All Categories';
        const cats = this.state.data.product_categories || [];
        if (count === 1) {
            const c = cats.find(x => x.id === this.state.priceTendency.selectedCategoryIds[0]);
            return c ? c.name : '1 Category';
        }
        return `${count} Categories`;
    }

    renderPriceTendencyChart() {
        const canvas = document.getElementById('priceTendencyChart');
        if (!canvas || !window.Chart) return;
        const data = this.state.priceTendency.data;
        if (!data || !data.labels || data.labels.length === 0) {
            if (this.priceTendencyChart) {
                this.priceTendencyChart.destroy();
                this.priceTendencyChart = null;
            }
            return;
        }

        if (this.priceTendencyChart) {
            this.priceTendencyChart.destroy();
            this.priceTendencyChart = null;
        }

        const datasets = data.datasets.map(ds => ({
            label: ds.label,
            data: ds.data,
            borderColor: ds.color,
            backgroundColor: ds.color + '22',
            fill: false,
            tension: 0.35,
            borderWidth: 2,
            pointRadius: 3,
            spanGaps: true,
        }));

        this.priceTendencyChart = new window.Chart(canvas, {
            type: 'line',
            data: { labels: data.labels, datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'nearest', intersect: true },
                onHover: (evt, activeElements) => {
                    evt.chart.canvas.style.cursor = activeElements.length ? 'pointer' : 'default';
                },
                onClick: (evt, activeElements) => {
                    if (activeElements && activeElements.length > 0) {
                        const firstPoint = activeElements[0];
                        const datasetIndex = firstPoint.datasetIndex;
                        const labelIndex = firstPoint.index;

                        const dataset = this.priceTendencyChart.data.datasets[datasetIndex];
                        const product = dataset.label;
                        const bucket = data.buckets[labelIndex];

                        if (product && bucket) {
                            this.openPriceTendencyDetail(product, bucket);
                        }
                    }
                },
                plugins: {
                    legend: { position: 'top', labels: { boxWidth: 12, font: { size: 11 } } },
                    tooltip: {
                        callbacks: {
                            label: ctx => `${ctx.dataset.label}: ₹${(ctx.parsed.y || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: false,
                        ticks: {
                            callback: v => '₹' + (v >= 100000 ? (v / 100000).toFixed(1) + 'L' : v.toLocaleString('en-IN'))
                        }
                    },
                    x: { ticks: { maxRotation: 45 } }
                }
            }
        });
    }

    async onExcludeBranchesChange(ev) {
        this.state.filters.exclude_branches = ev.target.value;
        await this.refreshDashboard();
        await this.loadPriceTendency();
    }

    openPriceTendencyDetail(productName, bucket) {
        const granularity = this.state.priceTendency.granularity;
        const domain = [
            ['product_id.name', '=', productName],
            ['state', 'in', ['purchase', 'done']]
        ];

        if (granularity === 'day') {
            domain.push(['order_id.date_order', '>=', bucket + ' 00:00:00']);
            domain.push(['order_id.date_order', '<=', bucket + ' 23:59:59']);
        } else if (granularity === 'month') {
            const [year, month] = bucket.split('-').map(Number);
            const firstDay = `${year}-${String(month).padStart(2, '0')}-01`;
            const lastDayNum = new Date(year, month, 0).getDate();
            const lastDay = `${year}-${String(month).padStart(2, '0')}-${String(lastDayNum).padStart(2, '0')}`;
            domain.push(['order_id.date_order', '>=', firstDay + ' 00:00:00']);
            domain.push(['order_id.date_order', '<=', lastDay + ' 23:59:59']);
        } else if (granularity === 'week') {
            const [year, week] = bucket.split('-').map(Number);
            const simple = new Date(year, 0, 4);
            const dayOfWeek = simple.getDay();
            const ISO_dayOfWeek = dayOfWeek === 0 ? 7 : dayOfWeek;
            const startOfWeek1 = new Date(simple.getTime() - (ISO_dayOfWeek - 1) * 86400000);
            const startOfTargetWeek = new Date(startOfWeek1.getTime() + (week - 1) * 7 * 86400000);
            const endOfTargetWeek = new Date(startOfTargetWeek.getTime() + 6 * 86400000);

            const pad = n => String(n).padStart(2, '0');
            const startStr = `${startOfTargetWeek.getFullYear()}-${pad(startOfTargetWeek.getMonth() + 1)}-${pad(startOfTargetWeek.getDate())}`;
            const endStr = `${endOfTargetWeek.getFullYear()}-${pad(endOfTargetWeek.getMonth() + 1)}-${pad(endOfTargetWeek.getDate())}`;
            domain.push(['order_id.date_order', '>=', startStr + ' 00:00:00']);
            domain.push(['order_id.date_order', '<=', endStr + ' 23:59:59']);
        }

        this.openModelList('purchase.order.line', domain, {
            useDateFilter: false,
            name: `${productName} (${bucket})`
        });
    }

    // Helper functions for formatting in QWeb template
    formatValue(val) {
        if (!val) return '0.00';
        if (val >= 10000000) {
            return (val / 10000000).toFixed(2) + ' Cr';
        } else if (val >= 100000) {
            return (val / 100000).toFixed(2) + ' L';
        }
        return val.toLocaleString('en-IN', { maximumFractionDigits: 2 });
    }

    formatQty(val) {
        if (!val) return '0';
        return Math.round(val).toLocaleString('en-IN');
    }

    _getDateDomain(dateField) {
        const domain = [];
        const filters = this.state.filters;
        if (filters.date_from) {
            domain.push([dateField, '>=', filters.date_from]);
        }
        if (filters.date_to) {
            domain.push([dateField, '<=', filters.date_to]);
        }
        if (!filters.date_from && !filters.date_to) {
            let y = filters.year;
            if (y !== 'all') {
                const yearVal = parseInt(y);
                if (filters.month === 'all') {
                    domain.push([dateField, '>=', `${yearVal}-01-01`]);
                    domain.push([dateField, '<=', `${yearVal}-12-31`]);
                } else {
                    const monthsMap = {
                        'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04', 'May': '05', 'Jun': '06',
                        'Jul': '07', 'Aug': '08', 'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'
                    };
                    const m = monthsMap[filters.month];
                    const daysInMonth = new Date(yearVal, parseInt(m), 0).getDate();
                    domain.push([dateField, '>=', `${yearVal}-${m}-01`]);
                    domain.push([dateField, '<=', `${yearVal}-${m}-${daysInMonth}`]);
                }
            }
        }
        return domain;
    }

    exportToExcel() {
        const companyId = this.companyService.currentCompany.id;
        const activeCompanyIds = (this.companyService.activeCompanyIds || [companyId]).join(',');
        const filters = this.state.filters;
        const catIds = filters.category_ids.join(',');
        const partnerIds = (filters.partner_ids || []).join(',');
        const excludePartnerIds = (filters.exclude_partner_ids || []).join(',');
        const url = `/purchase_dashboard/export_xlsx?company_id=${companyId}&company_ids=${activeCompanyIds}` +
            `&year=${filters.year}` +
            `&month=${filters.month}` +
            `&date_from=${filters.date_from || ''}` +
            `&date_to=${filters.date_to || ''}` +
            `&category_ids=${catIds}` +
            `&partner_ids=${partnerIds}` +
            `&exclude_partner_ids=${excludePartnerIds}` +
            `&exclude_branches=${filters.exclude_branches === 'without'}`;
        window.location.href = url;
    }

    async openPendingPOLines(vendorId = null) {
        try {
            const currentCompanyId = this.companyService.currentCompany.id;
            const activeCompanyIds = (this.companyService.activeCompanyIds || [currentCompanyId]).map(id => parseInt(id));
            const partnerIds = vendorId ? [vendorId] : this.state.filters.partner_ids;
            const lineIds = await this.orm.call(
                "purchase.dashboard",
                "get_pending_po_line_ids",
                [],
                {
                    company_id: currentCompanyId,
                    company_ids: activeCompanyIds,
                    category_ids: this.state.filters.category_ids,
                    partner_ids: partnerIds,
                    exclude_partner_ids: this.state.filters.exclude_partner_ids,
                    exclude_branches: this.state.filters.exclude_branches === 'without',
                }
            );
            this.openModelList('purchase.order.line', [['id', 'in', lineIds]], { useDateFilter: false });
        } catch (e) {
            console.error("Error fetching pending PO line IDs:", e);
        }
    }

    // Open Delayed Deliveries list — matches exact SQL: state in ('assigned','confirmed'), scheduled_date < NOW()
    openDelayedDeliveries() {
        // Build a datetime string matching SQL NOW() so the list count matches the KPI
        const now = new Date();
        const pad = n => String(n).padStart(2, '0');
        const nowStr = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ` +
            `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;

        const domain = [
            ['picking_type_code', '=', 'incoming'],
            ['state', 'in', ['assigned', 'confirmed']],
            ['scheduled_date', '<', nowStr],
        ];
        this.openModelList('stock.picking', domain, {
            useDateFilter: false,
            name: 'Delayed Deliveries'
        });
    }

    // Interactive drill-down redirection action with filters
    openModelList(resModel, domain = [], options = {}) {
        let finalDomain = [...domain];
        if (options.useDateFilter && options.dateField) {
            finalDomain = finalDomain.concat(this._getDateDomain(options.dateField));
        }
        if (options.useCategoryFilter && options.categoryField && this.state.filters.category_ids.length > 0) {
            finalDomain = finalDomain.concat([[options.categoryField, 'child_of', this.state.filters.category_ids]]);
        }

        // Apply company filter based on dashboard branches resolution
        if (this.state.data.company_ids && this.state.data.company_ids.length > 0) {
            if (['purchase.order', 'purchase.order.line', 'account.move', 'stock.picking', 'employee.purchase.requisition', 'purchase.savings.report'].includes(resModel)) {
                finalDomain.push(['company_id', 'in', this.state.data.company_ids]);
            }
        }

        // Apply global branch exclusion to drill-downs if active
        if (this.state.filters.exclude_branches === 'without' && this.state.data.branch_partner_ids) {
            if (['purchase.order', 'purchase.order.line', 'account.move', 'stock.picking', 'purchase.savings.report'].includes(resModel)) {
                if (resModel === 'purchase.order.line') {
                    finalDomain.push(['order_id.partner_id', 'not in', this.state.data.branch_partner_ids]);
                } else {
                    finalDomain.push(['partner_id', 'not in', this.state.data.branch_partner_ids]);
                }
            }
        }

        const context = options.context || {};

        const views = options.viewId ? [[options.viewId, 'list'], [false, 'form']] : [[false, 'list'], [false, 'form']];
        this.actionService.doAction({
            type: 'ir.actions.act_window',
            name: options.name || _t('Dashboard Detail'),
            res_model: resModel,
            view_mode: 'list,form',
            views: views,
            domain: finalDomain,
            context: context,
            target: 'current',
        });
    }

    async openCriticalSuppliers() {
        try {
            const currentCompanyId = this.companyService.currentCompany.id;
            const activeCompanyIds = (this.companyService.activeCompanyIds || [currentCompanyId]).map(id => parseInt(id));
            const partnerIds = await this.orm.call(
                "purchase.dashboard",
                "get_critical_supplier_ids",
                [],
                {
                    company_id: currentCompanyId,
                    company_ids: activeCompanyIds,
                    exclude_partner_ids: this.state.filters.exclude_partner_ids,
                    exclude_branches: this.state.filters.exclude_branches === 'without',
                }
            );
            this.openModelList('res.partner', [['id', 'in', partnerIds]], {
                useDateFilter: false,
                name: 'Critical Suppliers'
            });
        } catch (e) {
            console.error("Error fetching critical supplier IDs:", e);
        }
    }

    onPOStatusClick(status) {
        if (status === 'PO Pending Approval') {
            this.openModelList('purchase.order', [['state', '=', 'pending_for_approval']], { useDateFilter: true, dateField: 'date_order', name: 'PO Pending Approval' });
        } else if (status === 'PO Released (Open PO)') {
            this.openModelList('purchase.order', [['state', 'in', ['purchase', 'done']], ['receipt_status', 'in', ['pending', 'partial']]], { useDateFilter: true, dateField: 'date_order', name: 'PO Released (Open PO)' });
        } else if (status === 'Gate Entry Done, GRN Pending') {
            this.orm.call('purchase.dashboard', 'get_gate_entry_done_grn_pending_picking_ids', [], {
                company_ids: this.state.data.company_ids || [this.companyService.currentCompany.id],
                year: this.state.filters.year,
                month: this.state.filters.month,
                date_from: this.state.filters.date_from,
                date_to: this.state.filters.date_to,
                exclude_partner_ids: this.state.filters.exclude_partner_ids,
                exclude_branches: this.state.filters.exclude_branches === 'without',
            }).then((pickingIds) => {
                this.openModelList('stock.picking', [
                    ['id', 'in', pickingIds]
                ], { useDateFilter: false, name: 'Gate Done, GRN Pending' });
            });
        } else if (status === 'Closed PO') {
            this.openModelList('purchase.order', [['state', 'in', ['purchase', 'done']], ['receipt_status', 'not in', ['pending', 'partial']]], { useDateFilter: true, dateField: 'date_order', name: 'Closed PO' });
        }
    }

    onRFQStatusClick(rfq) {
        if (rfq.status === 'Converted to PO') {
            this.openModelList('purchase.order', [['state', 'in', ['purchase', 'done']]], { useDateFilter: true, dateField: 'date_order', name: 'Converted to PO' });
        } else if (rfq.status === 'RFQ Created') {
            this.openModelList('purchase.order', [['state', 'in', ['draft', 'sent']]], { useDateFilter: true, dateField: 'date_order', name: 'RFQ Created (All)' });
        } else if (rfq.is_child && rfq.aging_type) {
            const d3 = new Date(Date.now() - 3 * 86400000).toISOString().split('T')[0];
            const d10 = new Date(Date.now() - 10 * 86400000).toISOString().split('T')[0];
            
            let domain = [['state', 'in', ['draft', 'sent']]];
            let name = '';
            
            if (rfq.aging_type === '1_3') {
                domain.push(['date_order', '>=', d3]);
                name = 'RFQ Aging (1-3 Days)';
            } else if (rfq.aging_type === '3_10') {
                domain.push(['date_order', '<', d3]);
                domain.push(['date_order', '>=', d10]);
                name = 'RFQ Aging (3-10 Days)';
            } else if (rfq.aging_type === '10_plus') {
                domain.push(['date_order', '<', d10]);
                name = 'RFQ Aging (10+ Days)';
            }
            
            this.openModelList('purchase.order', domain, { useDateFilter: true, dateField: 'date_order', name: name });
        }
    }

    // ---------- Price Comparison Methods ----------
    togglePcCategoryDropdown() {
        this.state.priceComparison.categoryDropdownOpen = !this.state.priceComparison.categoryDropdownOpen;
        this.state.priceComparison.productDropdownOpen = false;
        this.state.priceComparison.categorySearchQuery = '';
    }

    onPcCategorySearchInput(ev) {
        this.state.priceComparison.categorySearchQuery = ev.target.value;
    }

    async selectPcCategory(catId, catName) {
        this.state.priceComparison.selectedCategoryId = catId;
        this.state.priceComparison.selectedCategoryName = catName;
        this.state.priceComparison.selectedProductIds = [];
        this.state.priceComparison.productSearchQuery = '';
        this.state.priceComparison.categoryDropdownOpen = false;
        await this.loadPcProducts();
        await this.loadPriceComparison();
    }

    togglePcProductDropdown() {
        this.state.priceComparison.productDropdownOpen = !this.state.priceComparison.productDropdownOpen;
        this.state.priceComparison.categoryDropdownOpen = false;
        this.state.priceComparison.productSearchQuery = '';
    }

    onPcProductSearchInput(ev) {
        this.state.priceComparison.productSearchQuery = ev.target.value;
    }

    async onPcProductToggle(productId) {
        const ids = [...this.state.priceComparison.selectedProductIds];
        const idx = ids.indexOf(productId);
        if (idx > -1) {
            ids.splice(idx, 1);
        } else {
            ids.push(productId);
        }
        this.state.priceComparison.selectedProductIds = ids;
        await this.loadPriceComparison();
    }

    async clearPcProducts() {
        this.state.priceComparison.selectedProductIds = [];
        this.state.priceComparison.productDropdownOpen = false;
        await this.loadPriceComparison();
    }

    async loadPcProducts() {
        try {
            const companyId = this.companyService.currentCompany.id;
            const activeCompanyIds = (this.companyService.activeCompanyIds || [companyId]).map(id => parseInt(id));
            const products = await this.orm.call(
                'purchase.dashboard',
                'get_products_by_category',
                [],
                {
                    company_id: companyId,
                    company_ids: activeCompanyIds,
                    category_id: this.state.priceComparison.selectedCategoryId,
                }
            );
            this.state.priceComparison.products = products;
        } catch (e) {
            console.error('Error loading products by category:', e);
        }
    }

    async loadPriceComparison() {
        try {
            sessionStorage.setItem('purchase_dashboard_pc_filters', JSON.stringify({
                selectedCategoryId: this.state.priceComparison.selectedCategoryId,
                selectedCategoryName: this.state.priceComparison.selectedCategoryName,
                selectedProductIds: this.state.priceComparison.selectedProductIds,
            }));
            this.state.priceComparison.loading = true;
            const companyId = this.companyService.currentCompany.id;
            const activeCompanyIds = (this.companyService.activeCompanyIds || [companyId]).map(id => parseInt(id));
            const res = await this.orm.call(
                'purchase.dashboard',
                'get_vendor_price_comparison',
                [],
                {
                    category_id: this.state.priceComparison.selectedCategoryId,
                    product_ids: this.state.priceComparison.selectedProductIds,
                    company_id: companyId,
                    company_ids: activeCompanyIds,
                    exclude_branches: this.state.filters.exclude_branches === 'without',
                    year: this.state.filters.year,
                    month: this.state.filters.month,
                    date_from: this.state.filters.date_from || null,
                    date_to: this.state.filters.date_to || null,
                    exclude_partner_ids: this.state.filters.exclude_partner_ids,
                }
            );
            this.state.priceComparison.vendors = res.vendors || [];
            this.state.priceComparison.rows = res.rows || [];
            this.state.priceComparison.loading = false;
        } catch (e) {
            console.error('Error loading price comparison:', e);
            this.state.priceComparison.loading = false;
        }
    }

    get filteredPcCategories() {
        const categories = this.state.data.product_categories || [];
        const query = (this.state.priceComparison.categorySearchQuery || '').toLowerCase().trim();
        if (!query) return categories;
        return categories.filter(c => (c.name || '').toLowerCase().includes(query));
    }

    get filteredPcProducts() {
        const products = this.state.priceComparison.products || [];
        const query = (this.state.priceComparison.productSearchQuery || '').toLowerCase().trim();
        if (!query) return products;
        return products.filter(p => (p.name || '').toLowerCase().includes(query));
    }

    isPcProductSelected(productId) {
        return this.state.priceComparison.selectedProductIds.includes(productId);
    }

    get priceComparisonProductLabel() {
        const count = this.state.priceComparison.selectedProductIds.length;
        if (count === 0) return 'All Products';
        return `${count} Product${count > 1 ? 's' : ''} Selected`;
    }

    exportPcToExcel() {
        const companyId = this.companyService.currentCompany.id;
        const activeCompanyIds = (this.companyService.activeCompanyIds || [companyId]).join(',');
        const filters = this.state.filters;
        const pc = this.state.priceComparison;
        const prodIds = pc.selectedProductIds.join(',');
        const excludePartnerIds = (filters.exclude_partner_ids || []).join(',');
        const url = `/purchase_dashboard/export_pc_xlsx?company_id=${companyId}&company_ids=${activeCompanyIds}` +
            `&category_id=${pc.selectedCategoryId || ''}` +
            `&product_ids=${prodIds}` +
            `&exclude_branches=${filters.exclude_branches === 'without'}` +
            `&year=${filters.year}` +
            `&month=${filters.month}` +
            `&date_from=${filters.date_from || ''}` +
            `&date_to=${filters.date_to || ''}` +
            `&exclude_partner_ids=${excludePartnerIds}`;
        window.location.href = url;
    }

    openPcBills(productId, vendorId) {
        const domain = [
            ['move_id.move_type', '=', 'in_invoice'],
            ['move_id.state', '=', 'posted'],
            ['partner_id', '=', vendorId],
            ['product_id', '=', productId]
        ];
        const viewId = this.state.data.move_line_view_id || false;
        this.openModelList('account.move.line', domain, {
            useDateFilter: false,
            name: `Vendor Bill Lines`,
            viewId: viewId
        });
    }

    openPcPos(productId, vendorId) {
        const domain = [
            ['order_id.state', 'in', ['purchase', 'done']],
            ['partner_id', '=', vendorId],
            ['product_id', '=', productId]
        ];
        this.openModelList('purchase.order.line', domain, {
            useDateFilter: false,
            name: `Purchase Order Lines`
        });
    }

    openPcBestPrice(row) {
        if (!row || row.min_price === null) return;
        const bestCell = row.cells.find(c => {
            const effPrice = c.last_bill !== null ? c.last_bill : c.last_po;
            return effPrice === row.min_price;
        });
        if (bestCell) {
            if (bestCell.last_bill === row.min_price) {
                this.openPcBills(row.product.id, bestCell.vendor_id);
            } else {
                this.openPcPos(row.product.id, bestCell.vendor_id);
            }
        }
    }

    openSavingsReport(dateFrom = null, dateTo = null) {
        let domain = [];
        if (dateFrom && dateTo) {
            domain.push(['invoice_date', '>=', dateFrom]);
            domain.push(['invoice_date', '<=', dateTo]);
        } else {
            domain = this._getDateDomain('invoice_date');
        }

        if (this.state.filters.category_ids.length > 0) {
            domain.push(['product_id.categ_id', 'child_of', this.state.filters.category_ids]);
        }

        if (this.state.filters.exclude_partner_ids.length > 0) {
            domain.push(['partner_id', 'not in', this.state.filters.exclude_partner_ids]);
        }

        this.openModelList('purchase.savings.report', domain, {
            useDateFilter: false,
            name: `Procurement Cost Savings`
        });
    }
}

// Register the custom OWL Purchase Dashboard component in actions registry
registry.category("actions").add("ss_purchase_dashboard_tag", PurchaseDashboard);
