class LanceViewer {
    constructor() {
        this.currentDataset = null;
        this.currentPage = 0;
        this.pageSize = 50;
        this.totalRows = 0;
        this.selectedColumns = [];
        this.allColumns = [];
        this.apiBase = window.location.origin;

        this.initializeElements();
        this.setupEventListeners();
        this.checkHealth();
        this.loadDatasets();
        this.initializeSelect2();
    }

    initializeElements() {
        this.elements = {
            healthStatus: document.getElementById('healthStatus'),
            datasetList: document.getElementById('datasetList'),
            datasetHeader: document.getElementById('datasetHeader'),
            datasetTitle: document.getElementById('datasetTitle'),
            columnSection: document.getElementById('columnSection'),
            schemaSection: document.getElementById('schemaSection'),
            schemaDisplay: document.getElementById('schemaDisplay'),
            dataSection: document.getElementById('dataSection'),
            dataTable: document.getElementById('dataTable'),
            tableHead: document.getElementById('tableHead'),
            tableBody: document.getElementById('tableBody'),
            dataLoading: document.getElementById('dataLoading'),
            dataError: document.getElementById('dataError'),
            columnSelect: document.getElementById('columnSelect'),
            prevPage: document.getElementById('prevPage'),
            nextPage: document.getElementById('nextPage'),
            pageInfo: document.getElementById('pageInfo'),
            pageSize: document.getElementById('pageSize'),
            selectAllCols: document.getElementById('selectAllCols'),
            selectNoneCols: document.getElementById('selectNoneCols'),
            applyColumns: document.getElementById('applyColumns'),
            tooltip: document.getElementById('tooltip'),
            toggleWordWrap: document.getElementById('toggleWordWrap'),
            wrapTextLabel: document.getElementById('wrapTextLabel')
        };
    }

    initializeSelect2() {
        // Initialize Select2 ONLY on the column selector
        setTimeout(() => {
            const $colSelect = $('#columnSelect');
            if ($colSelect.length && !$colSelect.data('select2')) {
                $colSelect.select2({
                    width: '100%',
                    dropdownParent: $colSelect.parent(),
                    placeholder: 'Select columns...',
                    allowClear: true
                });
            }
        }, 100);
    }

    setupEventListeners() {
        this.elements.prevPage.addEventListener('click', () => this.previousPage());
        this.elements.nextPage.addEventListener('click', () => this.nextPage());
        this.elements.pageSize.addEventListener('change', (e) => {
            this.pageSize = parseInt(e.target.value);
            this.currentPage = 0;
            this.loadData();
        });

        this.elements.selectAllCols.addEventListener('click', () => this.selectAllColumns());
        this.elements.selectNoneCols.addEventListener('click', () => this.selectNoColumns());
        this.elements.applyColumns.addEventListener('click', () => this.applyColumnSelection());

        document.addEventListener('mousemove', (e) => this.updateTooltipPosition(e));

        window.addEventListener('hashchange', () => {
            const hash = decodeURIComponent(window.location.hash.substring(1));
            if (hash && hash !== this.currentDataset) {
                this.selectDataset(hash);
            }
        });

        this.elements.toggleWordWrap.addEventListener('change', (e) => {
            if (e.target.checked) {
                this.elements.dataTable.classList.add('wrap-text');
            } else {
                this.elements.dataTable.classList.remove('wrap-text');
            }
            // Trigger DataTable redraw to adjust for layout changes
            if ($.fn.DataTable.isDataTable('#dataTable')) {
                $('#dataTable').DataTable().columns.adjust();
            }
        });

        // Initialize default state
        if (this.elements.toggleWordWrap.checked) {
            this.elements.dataTable.classList.add('wrap-text');
        }
    }

    async checkHealth() {
        try {
            const response = await fetch(`${this.apiBase}/healthz`);
            const data = await response.json();
            if (data.ok) {
                // Show Lance version prominently along with app version
                const lanceVersion = data.lancedb_version || 'unknown';
                const pyarrowVersion = data.pyarrow_version || 'unknown';
                this.elements.healthStatus.innerHTML = `
                    <div class="version-info">
                        <div class="app-version">Lance Data Viewer v${data.app_version}</div>
                        <div class="lance-version">LanceDB ${lanceVersion} • PyArrow ${pyarrowVersion}</div>
                    </div>
                `;
                this.elements.healthStatus.className = 'health-status healthy';
            } else {
                throw new Error('Health check failed');
            }
        } catch (error) {
            this.elements.healthStatus.textContent = 'Connection Error';
            this.elements.healthStatus.className = 'health-status error';
        }
    }

    async loadDatasets() {
        try {
            const response = await fetch(`${this.apiBase}/datasets`);
            const data = await response.json();

            this.elements.datasetList.innerHTML = '';

            if (data.datasets.length === 0) {
                this.elements.datasetList.innerHTML = '<div class="loading">No datasets found</div>';
                return;
            }

            data.datasets.forEach(dataset => {
                const item = document.createElement('div');
                item.className = 'dataset-item';
                item.setAttribute('data-name', dataset);
                item.textContent = dataset;
                item.addEventListener('click', () => {
                    window.location.hash = encodeURIComponent(dataset);
                });
                this.elements.datasetList.appendChild(item);
            });

            // Handle initial direct link via hash
            const initialHash = decodeURIComponent(window.location.hash.substring(1));
            if (initialHash && data.datasets.includes(initialHash)) {
                this.selectDataset(initialHash);
            }
        } catch (error) {
            this.elements.datasetList.innerHTML = '<div class="error">Failed to load datasets</div>';
        }
    }

    async selectDataset(datasetName) {
        document.querySelectorAll('.dataset-item').forEach(item => {
            if (item.getAttribute('data-name') === datasetName) {
                item.classList.add('active');
            } else {
                item.classList.remove('active');
            }
        });

        if (this.currentDataset === datasetName) return;

        this.currentDataset = datasetName;
        this.currentPage = 0;
        this.elements.datasetTitle.textContent = datasetName;
        this.elements.datasetHeader.style.display = 'block';

        await this.loadSchema();
        await this.loadColumns();
        await this.loadData();
    }

    async loadSchema() {
        try {
            const response = await fetch(`${this.apiBase}/datasets/${this.currentDataset}/schema`);
            const schema = await response.json();

            this.elements.schemaDisplay.innerHTML = '';
            schema.fields.forEach(field => {
                const fieldDiv = document.createElement('div');
                const isVector = field.type.includes('list<item: double>') || field.type.includes('fixed_size_list<item: float>');
                fieldDiv.className = isVector ? 'schema-field vector' : 'schema-field';

                let typeDisplay;
                if (isVector) {
                    // Check if this is a CLIP vector
                    if (field.type.includes('[512]')) {
                        typeDisplay = `${field.name}: CLIP vector (512-dim float)`;
                    } else {
                        typeDisplay = `${field.name}: vector (${field.type})`;
                    }
                } else {
                    typeDisplay = `${field.name}: ${field.type}`;
                }

                fieldDiv.textContent = typeDisplay;
                this.elements.schemaDisplay.appendChild(fieldDiv);
            });

            this.elements.schemaSection.style.display = 'block';
        } catch (error) {
            this.showError('Failed to load schema');
        }
    }

    async loadColumns() {
        try {
            const response = await fetch(`${this.apiBase}/datasets/${this.currentDataset}/columns`);
            const data = await response.json();

            this.allColumns = data.columns;
            this.selectedColumns = data.columns.map(col => col.name);

            this.elements.columnSelect.innerHTML = '';
            data.columns.forEach(column => {
                const option = document.createElement('option');
                option.value = column.name;
                option.textContent = column.is_vector
                    ? `${column.name} (vector)`
                    : column.name;
                option.selected = true;
                this.elements.columnSelect.appendChild(option);
            });

            this.elements.columnSelect.style.display = 'block';
            this.elements.columnSelect.parentElement.querySelector('.column-controls').style.display = 'flex';
            this.elements.columnSection.style.display = 'block';
            
            // Re-initialize Select2 for the updated columns
            this.initializeSelect2();
        } catch (error) {
            this.showError('Failed to load columns');
        }
    }

    selectAllColumns() {
        Array.from(this.elements.columnSelect.options).forEach(option => {
            option.selected = true;
        });
    }

    selectNoColumns() {
        Array.from(this.elements.columnSelect.options).forEach(option => {
            option.selected = false;
        });
    }

    applyColumnSelection() {
        this.selectedColumns = Array.from(this.elements.columnSelect.selectedOptions).map(option => option.value);
        this.currentPage = 0;
        this.loadData();
    }

    async loadData() {
        if (!this.currentDataset) return;
        
        // Hide our native pagination and controls since DataTables handles it
        this.elements.pageSize.parentElement.style.display = 'none';

        // Prepare columns array for DataTables
        const dtColumns = this.selectedColumns.map(colName => {
            return {
                data: colName,
                name: colName,
                title: colName,
                searchable: true,
                orderable: true,
                render: (data, type, row, meta) => {
                    // DataTables calls render for different property types
                    // We only want to transform for display
                    if (type !== 'display') return data;
                    
                    if (data && typeof data === 'object') {
                        if (data.type === 'vector') {
                            // We return a placeholder div that we'll populate after draw
                            return `<div class="dt-vector-placeholder" data-row="${meta.row}" data-col="${colName}"></div>`;
                        } else if (data.error) {
                            return `<span class="co-primitive">Error: ${data.error}</span>`;
                        } else {
                            // Complex object placeholder
                            return `<div class="dt-complex-placeholder" data-row="${meta.row}" data-col="${colName}"></div>`;
                        }
                    }
                    
                    // Simple text wrapping
                    if (typeof data === 'string') {
                        if (data.length > 500) {
                            return `<div class="dt-longtext-placeholder" data-row="${meta.row}" data-col="${colName}"></div>`;
                        } else if (data.length >= 40) {
                            return `<p class="dt-plain-text">${String(data)}</p>`;
                        }
                    }
                    
                    return data === null ? '<span class="co-null">null</span>' : String(data);
                }
            };
        });

        // Destroy existing instance if it exists
        if ($.fn.DataTable.isDataTable('#dataTable')) {
            $('#dataTable').DataTable().destroy();
            this.elements.tableHead.innerHTML = '';
            this.elements.tableBody.innerHTML = '';
        }

        this.elements.dataSection.style.display = 'block';

        const self = this;
        
        // Initialize DataTable with Server-Side Processing
        const table = $('#dataTable').DataTable({
            serverSide: true,
            processing: true,
            fixedHeader: {
                header: true,
                footer: false
            },
            colReorder: true,
            ajax: (data, callback, settings) => {
                fetch(`${this.apiBase}/datasets/${this.currentDataset}/datatables`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(data)
                })
                .then(response => {
                    if (!response.ok) {
                        return response.json().then(err => { throw err; });
                    }
                    return response.json();
                })
                .then(json => {
                    callback(json);
                })
                .catch(error => {
                    console.error('DataTables Ajax Error:', error);
                    let msg = error.message || 'Unknown error';
                    if (error.detail) msg = JSON.stringify(error.detail);
                    self.showError('DataTables Error: ' + msg);
                    callback({
                        draw: data.draw,
                        recordsTotal: 0,
                        recordsFiltered: 0,
                        data: []
                    });
                });
            },
            columns: dtColumns,
            order: [], // Default no ordering
            pageLength: this.pageSize,
            lengthMenu: [25, 50, 100, 200, 500, 1000],
            dom: '<"table-controls-top"lfpi>Qrt',
            searchBuilder: {
                logic: 'AND',
                liveSearch: false
            },
            language: {
                search: "",
                searchPlaceholder: "Search global...",
                processing: "Loading data from LanceDB..."
            },
            drawCallback: function(settings) {
                const api = this.api();
                const data = api.rows({page: 'current'}).data();
                
                // After table drawing, find placeholders and inject our custom vanilla JS renderers
                $(api.table().body()).find('.dt-vector-placeholder').each(function() {
                    const rowIdx = $(this).data('row');
                    const colName = $(this).data('col');
                    const cellData = data[rowIdx][colName];
                    self.renderVectorCell(this, cellData, colName);
                });
                
                $(api.table().body()).find('.dt-complex-placeholder').each(function() {
                    const rowIdx = $(this).data('row');
                    const colName = $(this).data('col');
                    const cellData = data[rowIdx][colName];
                    self.renderComplexObject(this, cellData, colName);
                });
                
                $(api.table().body()).find('.dt-longtext-placeholder').each(function() {
                    const rowIdx = $(this).data('row');
                    const colName = $(this).data('col');
                    const cellData = data[rowIdx][colName];
                    self.renderLongText(this, cellData);
                });
            }
        });

        // Sync page size changes back to our property just in case
        table.on('length.dt', function(e, settings, len) {
            self.pageSize = len;
            self.elements.pageSize.value = len;
        });

        // Move all controls to the external container
        const toolbarContainer = document.getElementById('tableToolbarContainer');
        toolbarContainer.innerHTML = '';
        
        // Move SearchBuilder
        const dtsb = this.elements.dataSection.querySelector('.dtsb-searchBuilder');
        if (dtsb) {
            toolbarContainer.appendChild(dtsb);
        }
        
        // Move Combined Controls
        const dtControls = this.elements.dataSection.querySelector('.table-controls-top');
        if (dtControls) {
            // Move Wrap Text toggle to the left of the search bar
            const searchBar = dtControls.querySelector('.dataTables_filter, .dt-search');
            if (this.elements.wrapTextLabel && searchBar) {
                searchBar.parentNode.insertBefore(this.elements.wrapTextLabel, searchBar);
            }
            toolbarContainer.appendChild(dtControls);
        }
    }

    renderTable(rows) {
        // Obsolete: DataTables handles rendering now.
    }

    renderVectorCell(cell, vectorData, columnName) {
        cell.className = 'vector-cell';

        // Handle error cases
        if (vectorData.error) {
            cell.className = 'vector-cell error';
            cell.textContent = `Vector Error: ${vectorData.error}`;
            return;
        }

        const container = document.createElement('div');
        container.className = 'vector-preview';

        const info = document.createElement('div');
        info.className = 'vector-info';

        // Enhanced info display for CLIP vectors
        if (vectorData.model === 'likely_clip') {
            info.innerHTML = `
                <span class="vector-model">CLIP</span>
                <span class="vector-dim">dim: ${vectorData.dim}</span>
                <span class="vector-norm">norm: ${vectorData.norm.toFixed(3)}</span>
            `;
            if (vectorData.stats && vectorData.stats.normalized) {
                info.classList.add('normalized');
            }
        } else {
            info.textContent = `dim: ${vectorData.dim}, norm: ${vectorData.norm.toFixed(3)}`;
        }

        const canvas = document.createElement('canvas');
        canvas.className = 'vector-sparkline';
        canvas.width = 180;
        canvas.height = 20;

        const ctx = canvas.getContext('2d');
        if (vectorData.preview && vectorData.preview.length > 0) {
            this.drawSparkline(ctx, vectorData.preview, canvas.width, canvas.height);
        }

        canvas.addEventListener('mouseenter', (e) => {
            this.showTooltip(e, vectorData, columnName);
        });

        canvas.addEventListener('mouseleave', () => {
            this.hideTooltip();
        });

        container.appendChild(info);
        container.appendChild(canvas);
        cell.appendChild(container);
    }

    drawSparkline(ctx, values, width, height) {
        const padding = 2;
        const drawWidth = width - 2 * padding;
        const drawHeight = height - 2 * padding;

        const min = Math.min(...values);
        const max = Math.max(...values);
        const range = max - min || 1;

        ctx.clearRect(0, 0, width, height);

        ctx.strokeStyle = '#1976d2';
        ctx.lineWidth = 1.5;
        ctx.beginPath();

        values.forEach((value, index) => {
            const x = padding + (index / (values.length - 1)) * drawWidth;
            const y = padding + (1 - (value - min) / range) * drawHeight;

            if (index === 0) {
                ctx.moveTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        });

        ctx.stroke();
    }

    showTooltip(event, vectorData, columnName) {
        const tooltip = this.elements.tooltip;
        const content = tooltip.querySelector('.tooltip-content');

        let tooltipHtml = `<strong>${columnName}</strong><br>`;

        if (vectorData.model === 'likely_clip') {
            tooltipHtml += `
                <span class="model-badge">CLIP Embedding</span><br>
                ${vectorData.description}<br><br>
                Dimension: ${vectorData.dim}<br>
                Norm: ${vectorData.norm.toFixed(4)} ${vectorData.stats.normalized ? '(normalized ✓)' : ''}<br>
                Range: ${vectorData.min.toFixed(4)} to ${vectorData.max.toFixed(4)}<br>
                Mean: ${vectorData.mean.toFixed(4)}<br>
                Sparsity: ${(vectorData.stats.sparsity * 100).toFixed(1)}%<br>
                Positive ratio: ${(vectorData.stats.positive_ratio * 100).toFixed(1)}%<br><br>
                Preview: [${vectorData.preview.slice(0, 8).map(v => v.toFixed(3)).join(', ')}...]
            `;
        } else {
            tooltipHtml += `
                Dimension: ${vectorData.dim}<br>
                Norm: ${vectorData.norm.toFixed(4)}<br>
                Min: ${vectorData.min.toFixed(4)}<br>
                Max: ${vectorData.max.toFixed(4)}<br>
                Preview: [${vectorData.preview.slice(0, 8).map(v => v.toFixed(2)).join(', ')}...]
            `;
        }

        content.innerHTML = tooltipHtml;
        tooltip.style.display = 'block';
        this.updateTooltipPosition(event);
    }

    hideTooltip() {
        this.elements.tooltip.style.display = 'none';
    }

    updateTooltipPosition(event) {
        const tooltip = this.elements.tooltip;
        if (tooltip.style.display === 'none') return;

        tooltip.style.left = (event.pageX + 10) + 'px';
        tooltip.style.top = (event.pageY - 10) + 'px';
    }

    updatePagination() {
        const totalPages = Math.ceil(this.totalRows / this.pageSize);
        const currentPageDisplay = this.currentPage + 1;

        this.elements.pageInfo.textContent = `Page ${currentPageDisplay} of ${totalPages} (${this.totalRows} total)`;
        this.elements.prevPage.disabled = this.currentPage === 0;
        this.elements.nextPage.disabled = this.currentPage >= totalPages - 1;
    }

    previousPage() {
        if (this.currentPage > 0) {
            this.currentPage--;
            this.loadData();
        }
    }

    nextPage() {
        const maxPage = Math.ceil(this.totalRows / this.pageSize) - 1;
        if (this.currentPage < maxPage) {
            this.currentPage++;
            this.loadData();
        }
    }

    showLoading() {
        this.elements.dataLoading.style.display = 'block';
        this.elements.dataError.style.display = 'none';
    }

    hideLoading() {
        this.elements.dataLoading.style.display = 'none';
    }

    showError(message) {
        this.elements.dataError.textContent = message;
        this.elements.dataError.style.display = 'block';
        this.elements.dataLoading.style.display = 'none';
    }


    renderComplexObject(container, obj, name) {
        const wrapper = document.createElement('div');
        wrapper.className = 'complex-object-wrapper';
        this._buildObjectDOM(wrapper, obj, name);
        container.appendChild(wrapper);
    }

    _buildObjectDOM(parent, obj, currentKey) {
        // 1. Handle Nulls
        if (obj === null) {
            const span = document.createElement('span');
            span.className = 'co-null';
            span.textContent = 'null';
            parent.appendChild(span);
            return;
        }

        // 2. Handle Primitives (Strings, Numbers, Booleans)
        if (typeof obj !== 'object') {
            const span = document.createElement('span');
            span.className = typeof obj === 'string' ? 'co-string' : 'co-primitive';
            
            if (typeof obj === 'string') {
                this.renderLongText(parent, `"${obj}"`, true);
            } else {
                span.textContent = String(obj);
                parent.appendChild(span);
            }
            return;
        }

        // 3. Handle Nested Vectors
        if (obj.type === 'vector') {
            // Wrap in a div to prevent renderVectorCell from overwriting container classes
            const vecWrap = document.createElement('div');
            this.renderVectorCell(vecWrap, obj, currentKey);
            parent.appendChild(vecWrap);
            return;
        }

       // 4. Handle Arrays
        if (Array.isArray(obj)) {
            const list = document.createElement('div');
            list.className = 'co-list';

            if (obj.length === 0) {
                const span = document.createElement('span');
                span.className = 'co-empty';
                span.textContent = '[]';
                parent.appendChild(span);
                return;
            }

            const LIMIT = 5;
            const hasHidden = obj.length > LIMIT;
            let hiddenContainer = null;

            obj.forEach((item, index) => {
                const itemDiv = document.createElement('div');
                itemDiv.className = 'co-list-item';
                
                const prefix = document.createElement('span');
                prefix.className = 'co-prefix';
                prefix.textContent = `[${index}]: `;
                itemDiv.appendChild(prefix);

                if (item && typeof item === 'object') {
                    const childContainer = document.createElement('div');
                    childContainer.className = 'co-child-container';
                    this._buildObjectDOM(childContainer, item, `${currentKey}[${index}]`);
                    itemDiv.appendChild(childContainer);
                } else {
                    this._buildObjectDOM(itemDiv, item, `${currentKey}[${index}]`);
                }

                // If we pass the limit, push to the hidden container instead
                if (hasHidden && index >= LIMIT) {
                    if (!hiddenContainer) {
                        hiddenContainer = document.createElement('div');
                        hiddenContainer.style.display = 'none';
                        list.appendChild(hiddenContainer);
                    }
                    hiddenContainer.appendChild(itemDiv);
                } else {
                    list.appendChild(itemDiv);
                }
            });

            if (hasHidden) {
                const toggleBtn = document.createElement('button');
                toggleBtn.className = 'co-toggle-btn';
                toggleBtn.textContent = `Show ${obj.length - LIMIT} more...`;
                toggleBtn.onclick = (e) => {
                    e.stopPropagation(); // Prevent triggering row selection
                    if (hiddenContainer.style.display === 'none') {
                        hiddenContainer.style.display = 'block';
                        toggleBtn.textContent = 'Show less';
                    } else {
                        hiddenContainer.style.display = 'none';
                        toggleBtn.textContent = `Show ${obj.length - LIMIT} more...`;
                    }
                };
                list.appendChild(toggleBtn);
            }

            parent.appendChild(list);
            return;
        }

        // 5. Handle Standard Dictionaries/Structs
        const dict = document.createElement('div');
        dict.className = 'co-dict';

        const keys = Object.keys(obj);
        if (keys.length === 0) {
            const span = document.createElement('span');
            span.className = 'co-empty';
            span.textContent = '{}';
            parent.appendChild(span);
            return;
        }

        const LIMIT = 5;
        const hasHidden = keys.length > LIMIT;
        let hiddenContainer = null;

        keys.forEach((key, index) => {
            const row = document.createElement('div');
            row.className = 'co-dict-row';

            const keySpan = document.createElement('strong');
            keySpan.className = 'co-key';
            keySpan.textContent = `${key}: `;
            row.appendChild(keySpan);

            const val = obj[key];
            if (val && typeof val === 'object') {
                const childContainer = document.createElement('div');
                childContainer.className = 'co-child-container';
                this._buildObjectDOM(childContainer, val, key);
                row.appendChild(childContainer);
            } else {
                this._buildObjectDOM(row, val, key);
            }

            // If we pass the limit, push to the hidden container instead
            if (hasHidden && index >= LIMIT) {
                if (!hiddenContainer) {
                    hiddenContainer = document.createElement('div');
                    hiddenContainer.style.display = 'none';
                    dict.appendChild(hiddenContainer);
                }
                hiddenContainer.appendChild(row);
            } else {
                dict.appendChild(row);
            }
        });

        if (hasHidden) {
            const toggleBtn = document.createElement('button');
            toggleBtn.className = 'co-toggle-btn';
            toggleBtn.textContent = `Show ${keys.length - LIMIT} more...`;
            toggleBtn.onclick = (e) => {
                e.stopPropagation();
                if (hiddenContainer.style.display === 'none') {
                    hiddenContainer.style.display = 'block';
                    toggleBtn.textContent = 'Show less';
                } else {
                    hiddenContainer.style.display = 'none';
                    toggleBtn.textContent = `Show ${keys.length - LIMIT} more...`;
                }
            };
            dict.appendChild(toggleBtn);
        }
        
        parent.appendChild(dict);
    }
    
    renderLongText(container, text, isCodeStyle = false) {
        const THRESHOLD = 500;
        if (!text || text.length <= THRESHOLD) {
            const span = document.createElement('span');
            if (isCodeStyle) span.className = 'co-string';
            span.textContent = text;
            container.appendChild(span);
            return;
        }

        const wrapper = document.createElement('div');
        wrapper.className = 'long-text-wrapper';
        
        const textSpan = document.createElement('span');
        textSpan.className = isCodeStyle ? 'co-string text-content' : 'text-content';
        const truncated = text.substring(0, THRESHOLD) + '...';
        textSpan.textContent = truncated;
        
        const toggleBtn = document.createElement('button');
        toggleBtn.className = 'co-toggle-btn';
        toggleBtn.textContent = 'Show more';
        
        let isExpanded = false;
        toggleBtn.onclick = (e) => {
            e.stopPropagation();
            isExpanded = !isExpanded;
            textSpan.textContent = isExpanded ? text : (text.substring(0, THRESHOLD) + '...');
            toggleBtn.textContent = isExpanded ? 'Show less' : 'Show more';
        };

        wrapper.appendChild(textSpan);
        wrapper.appendChild(toggleBtn);
        container.appendChild(wrapper);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new LanceViewer();
});