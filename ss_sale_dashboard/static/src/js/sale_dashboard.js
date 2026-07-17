/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState, useEffect } from "@odoo/owl";
import { Layout } from "@web/search/layout";
import { loadBundle } from "@web/core/assets";

export class SaleDashboard extends Component {
    static template = "ss_sale_dashboard.SaleDashboard";
    static components = { Layout };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.companyService = useService("company");

        // Debounce timer for date-field changes
        this._dateDebounceTimer = null;

        // Memoization cache for customer dropdown filtering
        this._customerFilterCache = { query: null, result: [] };

        this.display = {
            controlPanel: {
                "top-left": true,
                "top-right": false,
                "bottom-left": false,
                "bottom-right": false,
            }
        };

        // Load filters from sessionStorage if available
        const savedFilters = sessionStorage.getItem('sale_dashboard_filters');
        let initialFilters = {
            year: '2026',
            month: 'all',
            date_from: '',
            date_to: '',
            exclude_branches: 'with', // 'with' or 'without'
            partner_ids: [],
            tds_filter: 'without_tds', // 'without_tds' or 'with_tds'
            categ_ids: [],
        };
        if (savedFilters) {
            try {
                initialFilters = JSON.parse(savedFilters);
                if (initialFilters.partner_id) {
                    initialFilters.partner_ids = initialFilters.partner_id !== 'all' ? [parseInt(initialFilters.partner_id)] : [];
                    delete initialFilters.partner_id;
                }
                if (initialFilters.categ_id) {
                    initialFilters.categ_ids = initialFilters.categ_id !== 'all' ? [parseInt(initialFilters.categ_id)] : [];
                    delete initialFilters.categ_id;
                }
            } catch (e) {
                console.error("Failed to parse saved filters:", e);
            }
        }

        // Load segment filters from sessionStorage if available
        const savedSegFilters = sessionStorage.getItem('sale_dashboard_seg_filters');
        let initialSegFilters = {
            year:         String(new Date().getFullYear()),
            compare_year: String(new Date().getFullYear() - 1),
            view:         'summary',   // 'summary' | 'detail'
            segment:      'HUPS',
        };
        if (savedSegFilters) {
            try {
                initialSegFilters = JSON.parse(savedSegFilters);
            } catch (e) {
                console.error("Failed to parse saved segment filters:", e);
            }
        }

        this.state = useState({
            data: {},
            loading: true,
            filters: initialFilters,
            searchableDropdown: {
                isOpen: false,
                searchQuery: '',
                selectedName: 'All Customers',
            },
            categoryDropdown: {
                isOpen: false,
                searchQuery: '',
                selectedName: 'All Categories',
            },
            // Segment Performance tab state
            segFilters: initialSegFilters,
            segData:    null,
            segLoading: false,
        });

        this.onYearChange = this.onYearChange.bind(this);
        this.onMonthChange = this.onMonthChange.bind(this);
        this.onDateFromChange = this.onDateFromChange.bind(this);
        this.onDateToChange = this.onDateToChange.bind(this);
        this.onExcludeBranchesChange = this.onExcludeBranchesChange.bind(this);
        this.resetFilters = this.resetFilters.bind(this);
        this.refreshDashboard = this.refreshDashboard.bind(this);
        this.exportToExcel = this.exportToExcel.bind(this);
        this.openSalesOrdersList = this.openSalesOrdersList.bind(this);
        this.openInvoicesList = this.openInvoicesList.bind(this);
        this.openPaymentsList = this.openPaymentsList.bind(this);
        this.openBankTransferList = this.openBankTransferList.bind(this);
        this.openCustomerOverdueInvoices = this.openCustomerOverdueInvoices.bind(this);
        this.openInvoiceForm = this.openInvoiceForm.bind(this);
        this.onTrendChartClick = this.onTrendChartClick.bind(this);
        this.onRegionChartClick = this.onRegionChartClick.bind(this);
        this.onProductChartClick = this.onProductChartClick.bind(this);
        this.onSegmentChartClick = this.onSegmentChartClick.bind(this);
        this.onProductSegmentChartClick = this.onProductSegmentChartClick.bind(this);
        this.onCategoryChartClick = this.onCategoryChartClick.bind(this);
        this.openFilteredInvoices = this.openFilteredInvoices.bind(this);
        this.openAgedReceivables = this.openAgedReceivables.bind(this);

        this.onDropdownFocus = this.onDropdownFocus.bind(this);
        this.onDropdownInput = this.onDropdownInput.bind(this);
        this.toggleDropdown = this.toggleDropdown.bind(this);
        this.toggleCustomer = this.toggleCustomer.bind(this);
        this.getFilteredCustomers = this.getFilteredCustomers.bind(this);

        this.onCategoryDropdownFocus = this.onCategoryDropdownFocus.bind(this);
        this.onCategoryDropdownInput = this.onCategoryDropdownInput.bind(this);
        this.toggleCategoryDropdown = this.toggleCategoryDropdown.bind(this);
        this.toggleCategory = this.toggleCategory.bind(this);
        this.getFilteredCategories = this.getFilteredCategories.bind(this);

        // Segment Performance handlers
        this.onSegYearChange       = this.onSegYearChange.bind(this);
        this.onSegCmpYearChange    = this.onSegCmpYearChange.bind(this);
        this.onSegViewChange       = this.onSegViewChange.bind(this);
        this.onSegSegmentChange    = this.onSegSegmentChange.bind(this);
        this.refreshSegmentData    = this.refreshSegmentData.bind(this);
        this.drillSegment          = this.drillSegment.bind(this);
        this.openSegmentOrders     = this.openSegmentOrders.bind(this);
        this.exportSegmentExcel    = this.exportSegmentExcel.bind(this);

        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            // Load static data (customers + categories) ONCE — not on every filter change
            await this.loadStaticData();
            await this.loadDashboardData();
            await this.loadSegmentData();
        });

        // Main Dashboard Charts Effect
        useEffect(() => {
            if (!this.state.loading && this.state.data.kpis) {
                this.renderCharts();
            }
            return () => {
                this.destroyCharts();
            };
        }, () => [this.state.loading, this.state.data]);

        // Searchable Customer & Category Dropdowns Outside Click Effect
        useEffect(() => {
            const handleOutsideClick = (ev) => {
                const container = document.getElementById("customer-dropdown-container");
                if (container && !container.contains(ev.target)) {
                    this.state.searchableDropdown.isOpen = false;
                    const len = this.state.filters.partner_ids.length;
                    if (len === 0) {
                        this.state.searchableDropdown.selectedName = 'All Customers';
                    } else if (len === 1) {
                        const customer = (this.state.data.customers || []).find(c => c.id === this.state.filters.partner_ids[0]);
                        if (customer) {
                            this.state.searchableDropdown.selectedName = customer.ref ? `[${customer.ref}] ${customer.name}` : customer.name;
                        }
                    } else {
                        this.state.searchableDropdown.selectedName = `${len} Customers Selected`;
                    }
                }

                const catContainer = document.getElementById("category-dropdown-container");
                if (catContainer && !catContainer.contains(ev.target)) {
                    this.state.categoryDropdown.isOpen = false;
                    const len = this.state.filters.categ_ids.length;
                    if (len === 0) {
                        this.state.categoryDropdown.selectedName = 'All Categories';
                    } else if (len === 1) {
                        const cat = (this.state.data.categories || []).find(c => c.id === this.state.filters.categ_ids[0]);
                        if (cat) {
                            this.state.categoryDropdown.selectedName = cat.complete_name || cat.name;
                        }
                    } else {
                        this.state.categoryDropdown.selectedName = `${len} Categories Selected`;
                    }
                }
            };
            document.addEventListener("mousedown", handleOutsideClick);
            return () => document.removeEventListener("mousedown", handleOutsideClick);
        }, () => [this.state.searchableDropdown.isOpen, this.state.categoryDropdown.isOpen]);
    }

    /**
     * Load customers, categories and branch partner IDs once at startup.
     * These are static lists that don't change with filter selections.
     */
    async loadStaticData() {
        try {
            const currentCompanyId = this.companyService.currentCompany.id;
            const activeCompanyIds = (this.companyService.activeCompanyIds || [currentCompanyId]).map(id => parseInt(id));
            const staticRes = await this.orm.call(
                "sale.dashboard",
                "get_static_data",
                [],
                {
                    exclude_branches: this.state.filters.exclude_branches === 'without',
                    company_id: currentCompanyId,
                    company_ids: activeCompanyIds,
                }
            );
            // Merge static data into state.data so templates can still access them
            this.state.data = Object.assign({}, this.state.data, {
                customers: staticRes.customers || [],
                categories: staticRes.categories || [],
                branch_partner_ids: staticRes.branch_partner_ids || [],
            });
            // Sync dropdown labels from persisted filter state
            this._syncDropdownLabels();
        } catch (e) {
            console.error("Error loading static dashboard data:", e);
        }
    }

    /** Sync dropdown display labels based on current filter selections. */
    _syncDropdownLabels() {
        const pLen = this.state.filters.partner_ids.length;
        if (pLen === 0) {
            this.state.searchableDropdown.selectedName = 'All Customers';
        } else if (pLen === 1) {
            const customer = (this.state.data.customers || []).find(c => c.id === this.state.filters.partner_ids[0]);
            if (customer) {
                this.state.searchableDropdown.selectedName = customer.ref ? `[${customer.ref}] ${customer.name}` : customer.name;
            } else {
                this.state.searchableDropdown.selectedName = 'All Customers';
                this.state.filters.partner_ids = [];
            }
        } else {
            this.state.searchableDropdown.selectedName = `${pLen} Customers Selected`;
        }

        const cLen = this.state.filters.categ_ids.length;
        if (cLen === 0) {
            this.state.categoryDropdown.selectedName = 'All Categories';
        } else if (cLen === 1) {
            const category = (this.state.data.categories || []).find(c => c.id === this.state.filters.categ_ids[0]);
            if (category) {
                this.state.categoryDropdown.selectedName = category.complete_name || category.name;
            } else {
                this.state.categoryDropdown.selectedName = 'All Categories';
                this.state.filters.categ_ids = [];
            }
        } else {
            this.state.categoryDropdown.selectedName = `${cLen} Categories Selected`;
        }
    }

    async loadDashboardData() {
        try {
            sessionStorage.setItem('sale_dashboard_filters', JSON.stringify(this.state.filters));
            this.state.loading = true;
            const currentCompanyId = this.companyService.currentCompany.id;
            const activeCompanyIds = (this.companyService.activeCompanyIds || [currentCompanyId]).map(id => parseInt(id));
            const res = await this.orm.call(
                "sale.dashboard",
                "get_dashboard_data",
                [],
                {
                    company_id: currentCompanyId,
                    company_ids: activeCompanyIds,
                    year: this.state.filters.year,
                    month: this.state.filters.month,
                    date_from: this.state.filters.date_from || null,
                    date_to: this.state.filters.date_to || null,
                    exclude_branches: this.state.filters.exclude_branches === 'without',
                    partner_ids: this.state.filters.partner_ids,
                    tds_filter: this.state.filters.tds_filter,
                    categ_ids: this.state.filters.categ_ids,
                }
            );
            // Merge with existing static data (customers/categories) — don't overwrite them
            this.state.data = Object.assign({}, this.state.data, res);
            this.state.loading = false;
            // Sync Segment tab on global filters load
            await this.loadSegmentData();
        } catch (e) {
            console.error("Error loading sales dashboard data:", e);
            this.state.loading = false;
            // Keep existing static data; only reset dynamic KPI fields
            this.state.data = Object.assign({}, this.state.data, {
                kpis: {
                    sales: 0, target: 0, achievement_pct: 0, collection: 0, outstanding: 0, overdue_outstanding: 0,
                    bank_received: 0, bank_partner_received: 0, bank_reconciled: 0, bank_suspense: 0, bank_reconciled_pct: 0
                },
                region_sales: [],
                product_sales: [],
                trend_sales: [],
                overdue_list: [],
                _error: true,
            });
        }
    }

    async refreshDashboard() {
        await this.loadDashboardData();
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

    onDateFromChange(ev) {
        this.state.filters.date_from = ev.target.value;
        if (ev.target.value) {
            this.state.filters.year = 'all';
            this.state.filters.month = 'all';
        }
        this._debouncedRefresh();
    }

    onDateToChange(ev) {
        this.state.filters.date_to = ev.target.value;
        if (ev.target.value) {
            this.state.filters.year = 'all';
            this.state.filters.month = 'all';
        }
        this._debouncedRefresh();
    }

    /** Debounce rapid date-field typing — fire refresh only after 400 ms of inactivity. */
    _debouncedRefresh() {
        if (this._dateDebounceTimer) {
            clearTimeout(this._dateDebounceTimer);
        }
        this._dateDebounceTimer = setTimeout(() => {
            this._dateDebounceTimer = null;
            this.refreshDashboard();
        }, 400);
    }

    async onExcludeBranchesChange(ev) {
        this.state.filters.exclude_branches = ev.target.value;
        await this.refreshDashboard();
    }


    async resetFilters() {
        this.state.filters.year = 'all';
        this.state.filters.month = 'all';
        this.state.filters.date_from = '';
        this.state.filters.date_to = '';
        this.state.filters.exclude_branches = 'with';
        this.state.filters.tds_filter = 'without_tds';
        this.state.filters.categ_ids = [];
        this.state.filters.partner_ids = [];
        this.state.searchableDropdown.selectedName = 'All Customers';
        this.state.searchableDropdown.searchQuery = '';
        this.state.searchableDropdown.isOpen = false;
        this.state.categoryDropdown.selectedName = 'All Categories';
        this.state.categoryDropdown.searchQuery = '';
        this.state.categoryDropdown.isOpen = false;
        await this.refreshDashboard();
    }

    exportToExcel() {
        const companyId = this.companyService.currentCompany.id;
        const activeCompanyIds = (this.companyService.activeCompanyIds || [companyId]).join(',');
        const { year, month, date_from, date_to, exclude_branches, partner_ids, tds_filter, categ_ids } = this.state.filters;

        let url = `/sale_dashboard/export_xlsx?company_id=${companyId}&company_ids=${activeCompanyIds}&year=${year}&month=${month}`;
        if (date_from) url += `&date_from=${date_from}`;
        if (date_to) url += `&date_to=${date_to}`;
        url += `&exclude_branches=${exclude_branches === 'without'}`;
        url += `&tds_filter=${tds_filter}`;
        if (categ_ids && categ_ids.length > 0) url += `&categ_ids=${categ_ids.join(',')}`;
        if (partner_ids && partner_ids.length > 0) url += `&partner_ids=${partner_ids.join(',')}`;

        window.location.href = url;
    }

    destroyCharts() {
        if (this.trendChart) {
            this.trendChart.destroy();
            this.trendChart = null;
        }
        if (this.regionChart) {
            this.regionChart.destroy();
            this.regionChart = null;
        }
        if (this.productChart) {
            this.productChart.destroy();
            this.productChart = null;
        }
        if (this.segmentChart) {
            this.segmentChart.destroy();
            this.segmentChart = null;
        }
        if (this.productSegmentChart) {
            this.productSegmentChart.destroy();
            this.productSegmentChart = null;
        }
        if (this.categoryChart) {
            this.categoryChart.destroy();
            this.categoryChart = null;
        }
    }

    renderCharts() {
        this.destroyCharts();

        const trendCtx = document.getElementById("trendChartCanvas");
        const regionCtx = document.getElementById("regionChartCanvas");
        const productCtx = document.getElementById("productChartCanvas");
        const segmentCtx = document.getElementById("segmentChartCanvas");
        const productSegmentCtx = document.getElementById("productSegmentChartCanvas");
        const categoryCtx = document.getElementById("categoryChartCanvas");

        // 1. Sales Trend Chart
        if (trendCtx && window.Chart && this.state.data.trend_sales) {
            const labels = this.state.data.trend_sales.map(d => d.month);
            const vals = this.state.data.trend_sales.map(d => d.amount);

            this.trendChart = new window.Chart(trendCtx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Monthly Sales (₹)',
                        data: vals,
                        borderColor: '#4F46E5',
                        backgroundColor: 'rgba(79, 70, 229, 0.1)',
                        fill: true,
                        tension: 0.3,
                        borderWidth: 3
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    onHover: (event, chartElement) => {
                        event.native.target.style.cursor = chartElement[0] ? 'pointer' : 'default';
                    },
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                callback: value => '₹' + value.toLocaleString()
                            }
                        }
                    },
                    onClick: (event, activeElements) => {
                        if (activeElements && activeElements.length > 0) {
                            const index = activeElements[0].index;
                            const label = labels[index];
                            this.onTrendChartClick(label);
                        }
                    }
                }
            });
        }

        // 2. Region-wise Sales Chart
        if (regionCtx && window.Chart && this.state.data.region_sales) {
            const labels = this.state.data.region_sales.map(d => d.region);
            const vals = this.state.data.region_sales.map(d => d.amount);

            this.regionChart = new window.Chart(regionCtx, {
                type: 'doughnut',
                data: {
                    labels: labels,
                    datasets: [{
                        data: vals,
                        backgroundColor: [
                            'rgba(79, 70, 229, 0.8)',
                            'rgba(16, 185, 129, 0.8)',
                            'rgba(245, 158, 11, 0.8)',
                            'rgba(239, 68, 68, 0.8)',
                            'rgba(14, 165, 233, 0.8)',
                            'rgba(139, 92, 246, 0.8)',
                        ],
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    onHover: (event, chartElement) => {
                        event.native.target.style.cursor = chartElement[0] ? 'pointer' : 'default';
                    },
                    plugins: {
                        legend: { position: 'right' }
                    },
                    onClick: (event, activeElements) => {
                        if (activeElements && activeElements.length > 0) {
                            const index = activeElements[0].index;
                            const label = labels[index];
                            this.onRegionChartClick(label);
                        }
                    }
                }
            });
        }

        // 3. Product-wise Sales Chart
        if (productCtx && window.Chart && this.state.data.product_sales) {
            const labels = this.state.data.product_sales.map(d => d.product);
            const vals = this.state.data.product_sales.map(d => d.amount);

            this.productChart = new window.Chart(productCtx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Sales Amount (₹)',
                        data: vals,
                        backgroundColor: 'rgba(16, 185, 129, 0.85)',
                        borderColor: '#10b981',
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    indexAxis: 'y',
                    onHover: (event, chartElement) => {
                        event.native.target.style.cursor = chartElement[0] ? 'pointer' : 'default';
                    },
                    scales: {
                        x: {
                            beginAtZero: true,
                            ticks: {
                                callback: value => '₹' + value.toLocaleString()
                            }
                        }
                    },
                    onClick: (event, activeElements) => {
                        if (activeElements && activeElements.length > 0) {
                            const index = activeElements[0].index;
                            const label = labels[index];
                            this.onProductChartClick(label);
                        }
                    }
                }
            });
        }

        // 4. Segment-wise Sales Chart
        if (segmentCtx && window.Chart && this.state.data.segment_sales) {
            const labels = this.state.data.segment_sales.map(d => d.segment);
            const vals = this.state.data.segment_sales.map(d => d.amount);

            this.segmentChart = new window.Chart(segmentCtx, {
                type: 'doughnut',
                data: {
                    labels: labels,
                    datasets: [{
                        data: vals,
                        backgroundColor: [
                            '#818CF8', '#34D399', '#FBBF24', '#F87171', '#60A5FA',
                            '#A78BFA', '#F472B6', '#34D399', '#FB7185', '#F59E0B'
                        ],
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    onHover: (event, chartElement) => {
                        event.native.target.style.cursor = chartElement[0] ? 'pointer' : 'default';
                    },
                    plugins: {
                        legend: {
                            position: 'right',
                            labels: {
                                font: { family: 'Segoe UI', size: 10 }
                            }
                        }
                    },
                    onClick: (event, activeElements) => {
                        if (activeElements && activeElements.length > 0) {
                            const index = activeElements[0].index;
                            const label = labels[index];
                            this.onSegmentChartClick(label);
                        }
                    }
                }
            });
        }

        // 4b. Product Segment-wise Sales Chart
        if (productSegmentCtx && window.Chart && this.state.data.product_segment_sales) {
            const labels = this.state.data.product_segment_sales.map(d => d.segment);
            const vals = this.state.data.product_segment_sales.map(d => d.amount);

            this.productSegmentChart = new window.Chart(productSegmentCtx, {
                type: 'doughnut',
                data: {
                    labels: labels,
                    datasets: [{
                        data: vals,
                        backgroundColor: [
                            '#34D399', '#60A5FA', '#FBBF24', '#F87171', '#818CF8',
                            '#A78BFA', '#F472B6', '#FB7185', '#F59E0B'
                        ],
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    onHover: (event, chartElement) => {
                        event.native.target.style.cursor = chartElement[0] ? 'pointer' : 'default';
                    },
                    plugins: {
                        legend: {
                            position: 'right',
                            labels: {
                                font: { family: 'Segoe UI', size: 10 }
                            }
                        }
                    },
                    onClick: (event, activeElements) => {
                        if (activeElements && activeElements.length > 0) {
                            const index = activeElements[0].index;
                            const label = labels[index];
                            this.onProductSegmentChartClick(label);
                        }
                    }
                }
            });
        }

        // 5. Product Category-wise Sales Chart
        if (categoryCtx && window.Chart && this.state.data.category_sales) {
            const labels = this.state.data.category_sales.map(d => d.category);
            const vals = this.state.data.category_sales.map(d => d.amount);

            this.categoryChart = new window.Chart(categoryCtx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Sales Amount (₹)',
                        data: vals,
                        backgroundColor: '#10B981',
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    indexAxis: 'y',
                    onHover: (event, chartElement) => {
                        event.native.target.style.cursor = chartElement[0] ? 'pointer' : 'default';
                    },
                    scales: {
                        x: {
                            beginAtZero: true,
                            ticks: {
                                callback: value => '₹' + value.toLocaleString()
                            }
                        }
                    },
                    onClick: (event, activeElements) => {
                        if (activeElements && activeElements.length > 0) {
                            const index = activeElements[0].index;
                            const label = labels[index];
                            this.onCategoryChartClick(label);
                        }
                    }
                }
            });
        }
    }

    openSalesOrdersList(scope) {
        const domain = [['move_type', '=', 'out_invoice'], ['state', '=', 'posted']];

        if (this.state.data.company_ids && this.state.data.company_ids.length > 0) {
            domain.push(['company_id', 'in', this.state.data.company_ids]);
        }

        if (this.state.filters.exclude_branches === 'without' && this.state.data.branch_partner_ids && this.state.data.branch_partner_ids.length > 0) {
            domain.push(['partner_id', 'not in', this.state.data.branch_partner_ids]);
        }

        if (this.state.filters.partner_ids && this.state.filters.partner_ids.length > 0) {
            domain.push(['partner_id', 'in', this.state.filters.partner_ids]);
        }

        if (this.state.filters.categ_ids && this.state.filters.categ_ids.length > 0) {
            domain.push(['invoice_line_ids.product_id.categ_id', 'child_of', this.state.filters.categ_ids]);
        }

        const dateDomain = this._getDateDomain('invoice_date');
        domain.push(...dateDomain);

        this.actionService.doAction({
            type: 'ir.actions.act_window',
            name: 'Invoiced Sales',
            res_model: 'account.move',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: domain,
            context: { default_move_type: 'out_invoice' },
            target: 'current',
        });
    }

    openInvoicesList(scope) {
        const domain = [['move_type', '=', 'out_invoice'], ['state', '=', 'posted'], ['payment_state', 'in', ['not_paid', 'partial']]];

        if (this.state.data.company_ids && this.state.data.company_ids.length > 0) {
            domain.push(['company_id', 'in', this.state.data.company_ids]);
        }

        if (this.state.filters.exclude_branches === 'without' && this.state.data.branch_partner_ids && this.state.data.branch_partner_ids.length > 0) {
            domain.push(['partner_id', 'not in', this.state.data.branch_partner_ids]);
        }

        if (this.state.filters.partner_ids && this.state.filters.partner_ids.length > 0) {
            domain.push(['partner_id', 'in', this.state.filters.partner_ids]);
        }

        if (this.state.filters.categ_ids && this.state.filters.categ_ids.length > 0) {
            domain.push(['invoice_line_ids.product_id.categ_id', 'child_of', this.state.filters.categ_ids]);
        }

        const dateDomain = this._getDateDomain('invoice_date');
        domain.push(...dateDomain);

        if (scope === 'overdue') {
            const todayStr = new Date().toISOString().split('T')[0];
            domain.push(['invoice_date_due', '<', todayStr]);
        }

        this.actionService.doAction({
            type: 'ir.actions.act_window',
            name: scope === 'overdue' ? 'Overdue Outstanding Invoices' : 'All Outstanding Invoices',
            res_model: 'account.move',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: domain,
            context: { default_move_type: 'out_invoice' },
            target: 'current',
        });
    }

    async openPaymentsList() {
        const currentCompanyId = this.companyService.currentCompany.id;
        const activeCompanyIds = (this.companyService.activeCompanyIds || [currentCompanyId]).map(id => parseInt(id));
        const lineIds = await this.orm.call(
            "sale.dashboard",
            "get_collection_line_ids",
            [],
            {
                company_id: currentCompanyId,
                company_ids: activeCompanyIds,
                year: this.state.filters.year,
                month: this.state.filters.month,
                date_from: this.state.filters.date_from || null,
                date_to: this.state.filters.date_to || null,
                exclude_branches: this.state.filters.exclude_branches === 'without',
                partner_ids: this.state.filters.partner_ids,
                tds_filter: this.state.filters.tds_filter,
                categ_ids: this.state.filters.categ_ids,
            }
        );

        this.actionService.doAction({
            type: 'ir.actions.act_window',
            name: this.state.filters.tds_filter === 'with_tds' ? 'Collections Detail (With TDS/TCS)' : 'Collections Detail (Bank/Cash)',
            res_model: 'account.move.line',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: [['id', 'in', lineIds]],
            target: 'current',
        });
    }

    async openBankTransferList(type) {
        const currentCompanyId = this.companyService.currentCompany.id;
        const activeCompanyIds = (this.companyService.activeCompanyIds || [currentCompanyId]).map(id => parseInt(id));
        const lineIds = await this.orm.call(
            "sale.dashboard",
            "get_bank_kpi_line_ids",
            [],
            {
                kpi_type: type,
                company_id: currentCompanyId,
                company_ids: activeCompanyIds,
                year: this.state.filters.year,
                month: this.state.filters.month,
                date_from: this.state.filters.date_from || null,
                date_to: this.state.filters.date_to || null,
                exclude_branches: this.state.filters.exclude_branches === 'without',
                partner_ids: this.state.filters.partner_ids,
            }
        );

        let title = 'Bank Transfers Received';
        if (type === 'partner_received') {
            title = 'Partner Bank Received';
        } else if (type === 'reconciled') {
            title = 'Reconciled Bank Amount';
        } else if (type === 'suspense') {
            title = 'Suspense Account Amount';
        }

        this.actionService.doAction({
            type: 'ir.actions.act_window',
            name: title,
            res_model: type === 'suspense' ? 'account.bank.statement.line' : 'account.move.line',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: [['id', 'in', lineIds]],
            target: 'current',
        });
    }

    openInvoiceForm(invoiceId) {
        this.actionService.doAction({
            type: 'ir.actions.act_window',
            res_model: 'account.move',
            res_id: invoiceId,
            views: [[false, 'form']],
            target: 'current',
        });
    }

    openCustomerOverdueInvoices(partnerId) {
        const todayStr = new Date().toISOString().split('T')[0];
        const domain = [
            ['move_type', '=', 'out_invoice'],
            ['state', '=', 'posted'],
            ['payment_state', 'in', ['not_paid', 'partial']],
            ['invoice_date_due', '<', todayStr],
            ['partner_id', '=', partnerId]
        ];

        if (this.state.data.company_ids && this.state.data.company_ids.length > 0) {
            domain.push(['company_id', 'in', this.state.data.company_ids]);
        }

        this.actionService.doAction({
            type: 'ir.actions.act_window',
            name: 'Customer Overdue Invoices',
            res_model: 'account.move',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: domain,
            context: { default_move_type: 'out_invoice' },
            target: 'current',
        });
    }

    _getDateDomain(dateField, filtersOverride = null) {
        const domain = [];
        const filters = filtersOverride || this.state.filters;
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
                    if (m) {
                        const daysInMonth = new Date(yearVal, parseInt(m), 0).getDate();
                        domain.push([dateField, '>=', `${yearVal}-${m}-01`]);
                        domain.push([dateField, '<=', `${yearVal}-${m}-${daysInMonth}`]);
                    }
                }
            }
        }
        return domain;
    }

    openFilteredInvoices(extraDomain = [], title = 'Filtered Invoices', resModel = 'account.move', dateFiltersOverride = null) {
        const domain = [];
        if (resModel === 'account.move') {
            domain.push(['state', '=', 'posted']);
            domain.push(['move_type', '=', 'out_invoice']);
        } else if (resModel === 'account.move.line') {
            domain.push(['move_id.state', '=', 'posted']);
            domain.push(['move_id.move_type', '=', 'out_invoice']);
            domain.push(['display_type', '=', 'product']);
        } else if (resModel === 'sale.report') {
            domain.push(['state', '!=', 'cancel']);
            domain.push(['invoice_id', '!=', false]);
            domain.push(['invoice_id.state', '=', 'posted']);
            domain.push(['qty_delivered', '>', 0]);
        }

        if (this.state.data.company_ids && this.state.data.company_ids.length > 0) {
            domain.push(['company_id', 'in', this.state.data.company_ids]);
        }

        if (this.state.filters.exclude_branches === 'without' && this.state.data.branch_partner_ids && this.state.data.branch_partner_ids.length > 0) {
            domain.push(['partner_id', 'not in', this.state.data.branch_partner_ids]);
        }

        if (this.state.filters.partner_ids && this.state.filters.partner_ids.length > 0) {
            domain.push(['partner_id', 'in', this.state.filters.partner_ids]);
        }

        if (this.state.filters.categ_ids && this.state.filters.categ_ids.length > 0) {
            let catField;
            if (resModel === 'sale.report') {
                catField = 'categ_id';
            } else if (resModel === 'account.move') {
                catField = 'invoice_line_ids.product_id.categ_id';
            } else {
                catField = 'product_id.categ_id';
            }
            domain.push([catField, 'child_of', this.state.filters.categ_ids]);
        } else if (resModel === 'sale.report') {
            const allowedCategoryIds = (this.state.data.categories || []).map(c => c.id);
            if (allowedCategoryIds.length > 0) {
                domain.push(['categ_id', 'in', allowedCategoryIds]);
            }
        }

        const dateField = resModel === 'account.move' ? 'invoice_date' : 'date';
        const dateDomain = this._getDateDomain(dateField, dateFiltersOverride);
        domain.push(...dateDomain);

        // Add extra domain
        domain.push(...extraDomain);

        const context = {};
        if (resModel === 'account.move') {
            context.default_move_type = 'out_invoice';
        } else if (resModel === 'account.move.line') {
            context.default_move_id_move_type = 'out_invoice';
        }

        this.actionService.doAction({
            type: 'ir.actions.act_window',
            name: title,
            res_model: resModel,
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: domain,
            context: context,
            target: 'current',
        });
    }

    onTrendChartClick(monthOrDayLabel) {
        let dateFrom = null;
        let dateTo = null;
        const year = this.state.filters.year !== 'all' ? this.state.filters.year : new Date().getFullYear().toString();

        if (this.state.filters.month === 'all') {
            // Month clicked
            const monthsMap = {
                'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04', 'May': '05', 'Jun': '06',
                'Jul': '07', 'Aug': '08', 'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'
            };
            const m = monthsMap[monthOrDayLabel];
            if (m) {
                dateFrom = `${year}-${m}-01`;
                const lastDay = new Date(parseInt(year), parseInt(m), 0).getDate();
                dateTo = `${year}-${m}-${lastDay}`;
            }
        } else {
            // Day clicked
            const monthsMap = {
                'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04', 'May': '05', 'Jun': '06',
                'Jul': '07', 'Aug': '08', 'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'
            };
            const m = monthsMap[this.state.filters.month];
            const d = String(monthOrDayLabel).padStart(2, '0');
            dateFrom = `${year}-${m}-${d}`;
            dateTo = `${year}-${m}-${d}`;
        }

        if (dateFrom && dateTo) {
            this.openFilteredInvoices(
                [],
                `Sales Trend - ${monthOrDayLabel}`,
                'account.move',
                { year: 'all', month: 'all', date_from: dateFrom, date_to: dateTo }
            );
        }
    }

    onRegionChartClick(regionLabel) {
        const extraDomain = regionLabel === 'Unknown' ?
            [['partner_id.state_id', '=', false]] :
            [['partner_id.state_id.name', '=', regionLabel]];

        this.openFilteredInvoices(extraDomain, `Sales - Region: ${regionLabel}`);
    }

    onProductChartClick(productLabel) {
        // Find matching product in state data to get product_id
        const prodItem = (this.state.data.product_sales || []).find(p => p.product === productLabel);
        if (prodItem && prodItem.product_id) {
            this.openFilteredInvoices(
                [['invoice_line_ids.product_id', '=', prodItem.product_id]],
                `Sales - Product: ${productLabel}`
            );
        } else {
            this.openFilteredInvoices(
                [['invoice_line_ids.product_id.name', '=', productLabel]],
                `Sales - Product: ${productLabel}`
            );
        }
    }

    onSegmentChartClick(segmentLabel) {
        if (segmentLabel === 'No Segment') {
            this.openFilteredInvoices(
                [['partner_id.segment_ids', '=', false]],
                'Sales - Segment: No Segment'
            );
        } else {
            this.openFilteredInvoices(
                [['partner_id.segment_ids.name', '=', segmentLabel]],
                `Sales - Segment: ${segmentLabel}`
            );
        }
    }

    onProductSegmentChartClick(segmentLabel) {
        if (segmentLabel === 'Other') {
            this.openFilteredInvoices(
                [
                    ['categ_id.name', 'not ilike', '%PLATE%'],
                    ['categ_id.name', 'not ilike', '%TW%'],
                    ['categ_id.name', 'not ilike', '%VRLA%'],
                    ['categ_id.name', 'not ilike', '%IB%'],
                    ['categ_id.name', 'not ilike', '%HUPS%'],
                    ['categ_id.name', 'not ilike', '%SPGS%'],
                    ['categ_id.name', 'not ilike', '%LITHIUM%'],
                    ['categ_id.name', 'not ilike', '%LI-ION%'],
                    ['categ_id.name', 'not ilike', '%LI_ION%'],
                    ['categ_id.name', 'not ilike', '%Lithium%'],
                    ['categ_id.name', 'not ilike', '%AM%'],
                    ['categ_id.name', 'not ilike', '%ER%']
                ],
                'Sales - Product Segment: Other',
                'sale.report'
            );
        } else {
            let domain = [];
            if (segmentLabel === 'PLATE') {
                domain.push(['categ_id.name', 'ilike', '%PLATE%']);
            } else if (segmentLabel === '2W+VRLA') {
                domain.push('|', ['categ_id.name', 'ilike', '%TW%'], ['categ_id.name', 'ilike', '%VRLA%']);
            } else if (segmentLabel === 'IB') {
                domain.push(['categ_id.name', 'ilike', '%IB%']);
            } else if (segmentLabel === 'HUPS') {
                domain.push(['categ_id.name', 'ilike', '%HUPS%']);
            } else if (segmentLabel === 'PANEL') {
                domain.push(['categ_id.name', 'ilike', '%SPGS%']);
            } else if (segmentLabel === 'LITHIUM') {
                domain.push('|', '|', '|', ['categ_id.name', 'ilike', '%LITHIUM%'], ['categ_id.name', 'ilike', '%LI-ION%'], ['categ_id.name', 'ilike', '%LI_ION%'], ['categ_id.name', 'ilike', '%Lithium%']);
            } else if (segmentLabel === 'AM') {
                domain.push(['categ_id.name', 'ilike', '%AM%']);
            } else if (segmentLabel === 'ER') {
                domain.push(['categ_id.name', 'ilike', '%ER%']);
            }
            this.openFilteredInvoices(domain, `Sales - Product Segment: ${segmentLabel}`, 'sale.report');
        }
    }

    onCategoryChartClick(categoryLabel) {
        this.openFilteredInvoices(
            [['categ_id.name', '=', categoryLabel]],
            `Sales - Category: ${categoryLabel}`,
            'sale.report'
        );
    }

    onDropdownFocus() {
        this.state.searchableDropdown.isOpen = true;
        this.state.searchableDropdown.searchQuery = '';
    }

    onDropdownInput(ev) {
        this.state.searchableDropdown.isOpen = true;
        this.state.searchableDropdown.searchQuery = ev.target.value;
        this.state.searchableDropdown.selectedName = ev.target.value;
    }

    toggleDropdown() {
        this.state.searchableDropdown.isOpen = !this.state.searchableDropdown.isOpen;
        if (this.state.searchableDropdown.isOpen) {
            this.state.searchableDropdown.searchQuery = '';
        }
    }

    async toggleCustomer(partnerId, partnerName) {
        if (partnerId === 'all') {
            this.state.filters.partner_ids = [];
            this.state.searchableDropdown.selectedName = 'All Customers';
        } else {
            const index = this.state.filters.partner_ids.indexOf(partnerId);
            if (index > -1) {
                this.state.filters.partner_ids.splice(index, 1);
            } else {
                this.state.filters.partner_ids.push(partnerId);
            }
            const len = this.state.filters.partner_ids.length;
            if (len === 0) {
                this.state.searchableDropdown.selectedName = 'All Customers';
            } else if (len === 1) {
                const customer = (this.state.data.customers || []).find(c => c.id === this.state.filters.partner_ids[0]);
                this.state.searchableDropdown.selectedName = customer ? (customer.ref ? `[${customer.ref}] ${customer.name}` : customer.name) : partnerName;
            } else {
                this.state.searchableDropdown.selectedName = `${len} Customers Selected`;
            }
        }
        await this.refreshDashboard();
    }

    getFilteredCustomers() {
        const query = (this.state.searchableDropdown.searchQuery || '').toLowerCase().trim();
        // Return memoized result if query hasn't changed
        if (query === this._customerFilterCache.query) {
            return this._customerFilterCache.result;
        }
        const customers = this.state.data.customers || [];
        let result;
        if (!query || query === 'all customers') {
            result = customers.filter(c => c.name).slice(0, 100);
        } else {
            result = customers.filter(c => {
                const name = (c.name || '').toLowerCase();
                const ref = c.ref ? String(c.ref).toLowerCase() : '';
                return name.includes(query) || ref.includes(query);
            }).slice(0, 100);
        }
        this._customerFilterCache = { query, result };
        return result;
    }

    onCategoryDropdownFocus() {
        this.state.categoryDropdown.isOpen = true;
        this.state.categoryDropdown.searchQuery = '';
    }

    onCategoryDropdownInput(ev) {
        this.state.categoryDropdown.isOpen = true;
        this.state.categoryDropdown.searchQuery = ev.target.value;
        this.state.categoryDropdown.selectedName = ev.target.value;
    }

    toggleCategoryDropdown() {
        this.state.categoryDropdown.isOpen = !this.state.categoryDropdown.isOpen;
        if (this.state.categoryDropdown.isOpen) {
            this.state.categoryDropdown.searchQuery = '';
        }
    }

    async toggleCategory(catId, catCompleteName) {
        if (catId === 'all') {
            this.state.filters.categ_ids = [];
            this.state.categoryDropdown.selectedName = 'All Categories';
        } else {
            const index = this.state.filters.categ_ids.indexOf(catId);
            if (index > -1) {
                this.state.filters.categ_ids.splice(index, 1);
            } else {
                this.state.filters.categ_ids.push(catId);
            }
            const len = this.state.filters.categ_ids.length;
            if (len === 0) {
                this.state.categoryDropdown.selectedName = 'All Categories';
            } else if (len === 1) {
                const category = (this.state.data.categories || []).find(c => c.id === this.state.filters.categ_ids[0]);
                this.state.categoryDropdown.selectedName = category ? (category.complete_name || category.name) : catCompleteName;
            } else {
                this.state.categoryDropdown.selectedName = `${len} Categories Selected`;
            }
        }
        await this.refreshDashboard();
    }

    getFilteredCategories() {
        const query = (this.state.categoryDropdown.searchQuery || '').toLowerCase().trim();
        const categories = this.state.data.categories || [];
        if (!query || query === 'all categories') {
            return categories.slice(0, 200);
        }
        return categories.filter(c => {
            const name = (c.name || '').toLowerCase();
            const completeName = (c.complete_name || '').toLowerCase();
            return name.includes(query) || completeName.includes(query);
        }).slice(0, 200);
    }

    openAgedReceivables(bucket, rowPartnerId) {
        const today = new Date().toISOString().split('T')[0];
        const companyIds = this.state.data.company_ids || [this.companyService.currentCompany.id];
        const branchIds = this.state.data.branch_partner_ids || [];
        // Prefer the row-level partner over global filter
        const globalPartner = this.state.filters.partner_ids.length > 0 ? this.state.filters.partner_ids : null;
        const partnerId = rowPartnerId ? parseInt(rowPartnerId) : null;

        // Build base domain
        const domain = [
            ['move_type', '=', 'out_invoice'],
            ['state', '=', 'posted'],
            ['payment_state', 'in', ['not_paid', 'partial']],
            ['company_id', 'in', companyIds],
        ];

        if (branchIds.length > 0 && this.state.filters.exclude_branches === 'without') {
            domain.push(['partner_id', 'not in', branchIds]);
        }
        if (partnerId) {
            domain.push(['partner_id', '=', partnerId]);
        } else if (globalPartner) {
            domain.push(['partner_id', 'in', globalPartner]);
        }
        if (this.state.filters.categ_ids && this.state.filters.categ_ids.length > 0) {
            domain.push(['invoice_line_ids.product_id.categ_id', 'child_of', this.state.filters.categ_ids]);
        }

        // Bucket → due date range mapping (updated to 7 buckets)
        const bucketMap = {
            'not_due': { label: 'Not Yet Due', daysFrom: null, daysTo: null, notDue: true },
            'bucket_1_30': { label: '1–30 Days', daysFrom: 0, daysTo: 30 },
            'bucket_31_60': { label: '31–60 Days', daysFrom: 30, daysTo: 60 },
            'bucket_61_90': { label: '61–90 Days', daysFrom: 60, daysTo: 90 },
            'bucket_91_120': { label: '91–120 Days', daysFrom: 90, daysTo: 120 },
            'bucket_121_150': { label: '121–150 Days', daysFrom: 120, daysTo: 150 },
            'bucket_151_180': { label: '151–180 Days', daysFrom: 150, daysTo: 180 },
            'bucket_older': { label: 'Older (180+ Days)', daysFrom: 180, daysTo: null },
            'customer': { label: 'All Outstanding', daysFrom: null, daysTo: null, all: true },
        };

        const b = bucketMap[bucket];
        if (!b) return;

        const label = b.label + (partnerId ? ` — ${rowPartnerId ? '' : ''}Customer` : '');

        if (b.notDue) {
            domain.push(['invoice_date_due', '>=', today]);
        } else if (!b.all) {
            const todayDate = new Date(today);
            if (b.daysTo !== null) {
                const dueTo = new Date(todayDate);
                dueTo.setDate(dueTo.getDate() - b.daysFrom);
                domain.push(['invoice_date_due', '<', dueTo.toISOString().split('T')[0]]);
            }
            if (b.daysFrom !== null && b.daysTo !== null) {
                const dueFrom = new Date(todayDate);
                dueFrom.setDate(dueFrom.getDate() - b.daysTo);
                domain.push(['invoice_date_due', '>=', dueFrom.toISOString().split('T')[0]]);
            }
        }

        this.actionService.doAction({
            type: 'ir.actions.act_window',
            name: `Aged Receivables — ${b.label}`,
            res_model: 'account.move',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain,
            context: { default_move_type: 'out_invoice' },
            target: 'current',
        });
    }
    // ──────────────────────────────────────────────────────────────────
    // Segment Performance Methods
    // ──────────────────────────────────────────────────────────────────

    /**
     * Fetch segment × branch data from the server and store in state.segData.
     * Called once on startup and on every year/compare-year change.
     */
    async loadSegmentData() {
        this.state.segLoading = true;
        try {
            const currentCompanyId = this.companyService.currentCompany.id;
            const activeCompanyIds = (this.companyService.activeCompanyIds || [currentCompanyId]).map(id => parseInt(id));
            const result = await this.orm.call(
                'sale.dashboard',
                'get_segment_branch_data',
                [],
                {
                    company_id:       currentCompanyId,
                    company_ids:      activeCompanyIds,
                    year:             this.state.segFilters.year,
                    compare_year:     this.state.segFilters.compare_year,
                    exclude_branches: this.state.filters.exclude_branches === 'without',
                }
            );
            this.state.segData = result;
        } catch (e) {
            console.error('Segment data load failed:', e);
            this.state.segData = null;
        } finally {
            this.state.segLoading = false;
        }
    }

    saveSegFilters() {
        sessionStorage.setItem('sale_dashboard_seg_filters', JSON.stringify(this.state.segFilters));
    }

    onSegYearChange(ev) {
        this.state.segFilters.year = ev.target.value;
        this.saveSegFilters();
        this.loadSegmentData();
    }

    onSegCmpYearChange(ev) {
        this.state.segFilters.compare_year = ev.target.value;
        this.saveSegFilters();
        this.loadSegmentData();
    }

    onSegViewChange(ev) {
        this.state.segFilters.view = ev.target.value;
        this.saveSegFilters();
    }

    onSegSegmentChange(ev) {
        this.state.segFilters.segment = ev.target.value;
        this.saveSegFilters();
    }

    /** Triggered by the Refresh button — re-fetches data with current segFilters. */
    async refreshSegmentData() {
        await this.loadSegmentData();
    }

    /**
     * Clicking a segment row in summary view switches to detail view for that segment.
     * @param {string} seg  e.g. 'HUPS'
     */
    drillSegment(seg) {
        this.state.segFilters.segment = seg;
        this.state.segFilters.view    = 'detail';
        this.saveSegFilters();
    }

    /**
     * Open a filtered sale.order list view for the given segment (and optionally branch).
     * The server resolves the ILIKE segment matching and returns matching order IDs.
     *
     * @param {string}      seg     Product segment key, e.g. 'HUPS'
     * @param {string|null} branch  Branch name string, or null for all branches
     */
    async openSegmentOrders(seg, branch = null, month = null, yearOverride = null) {
        const year   = yearOverride || this.state.segFilters.year;
        let label    = branch ? `${seg} — ${branch}` : seg;
        if (month) {
            label += ` — ${month}`;
        }
        let result;
        try {
            const currentCompanyId   = this.companyService.currentCompany.id;
            const activeCompanyIds   = (this.companyService.activeCompanyIds || [currentCompanyId]).map(id => parseInt(id));
            result = await this.orm.call(
                'sale.dashboard',
                'get_segment_order_ids',
                [],
                {
                    segment:          seg,
                    year:             year,
                    branch_name:      branch || false,
                    month:            month || false,
                    exclude_branches: this.state.filters.exclude_branches === 'without',
                    company_id:       currentCompanyId,
                    company_ids:      activeCompanyIds,
                }
            );
        } catch (e) {
            console.error('openSegmentOrders failed:', e);
            return;
        }

        const ids = result ? (result.ids || []) : [];
        const valid_cat_ids = result ? (result.valid_cat_ids || []) : [];

        if (!ids || ids.length === 0) {
            // Show a friendly notification when no lines found
            this.env.services.notification.add(
                `No sale lines found for ${label} in ${year}.`,
                { type: 'warning', title: 'No Lines Found' }
            );
            return;
        }

        this.actionService.doAction({
            type:       'ir.actions.act_window',
            name:       `${label} \u2014 Sales Analysis (${year})`,
            res_model:  'sale.report',
            view_mode:  'list',
            views:      [[false, 'list']],
            domain:     [['id', 'in', ids], ['categ_id', 'in', valid_cat_ids], ['qty_invoiced', '>', 0.0]],
            context:    { 'target_segment': seg },
            target:     'current',
        });
    }

    exportSegmentExcel() {
        const companyId = this.companyService.currentCompany.id;
        const activeCompanyIds = (this.companyService.activeCompanyIds || [companyId]).join(',');
        const { year, compare_year } = this.state.segFilters;
        const exclude_branches = this.state.filters.exclude_branches === 'without';

        const url = `/sale_dashboard/export_segment_xlsx?company_id=${companyId}&company_ids=${activeCompanyIds}&year=${year}&compare_year=${compare_year}&exclude_branches=${exclude_branches}`;
        
        // Native HTML5 download trigger via temporary anchor element
        const link = document.createElement('a');
        link.href = url;
        link.setAttribute('download', `product_segment_performance_${year}_vs_${compare_year}.xlsx`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }
}


// Register OWL tag
registry.category("actions").add("ss_sale_dashboard_tag", SaleDashboard);
registry.category("actions").add("zunax_sale_dashboard_tag", SaleDashboard);
