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
            tooltip: document.getElementById('tooltip')
        };
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
                item.textContent = dataset;
                item.addEventListener('click', () => this.selectDataset(dataset));
                this.elements.datasetList.appendChild(item);
            });
        } catch (error) {
            this.elements.datasetList.innerHTML = '<div class="error">Failed to load datasets</div>';
        }
    }

    async selectDataset(datasetName) {
        document.querySelectorAll('.dataset-item').forEach(item => {
            item.classList.remove('active');
        });

        event.target.classList.add('active');

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

        this.showLoading();

        try {
            const params = new URLSearchParams({
                limit: this.pageSize.toString(),
                offset: (this.currentPage * this.pageSize).toString()
            });

            if (this.selectedColumns.length > 0 && this.selectedColumns.length < this.allColumns.length) {
                params.append('columns', this.selectedColumns.join(','));
            }

            const response = await fetch(`${this.apiBase}/datasets/${this.currentDataset}/rows?${params}`);
            const data = await response.json();

            this.totalRows = data.total;
            this.renderTable(data.rows);
            this.updatePagination();
            this.hideLoading();

        } catch (error) {
            this.hideLoading();
            this.showError('Failed to load data');
        }
    }

    renderTable(rows) {
        if (rows.length === 0) {
            this.elements.tableBody.innerHTML = '<tr><td colspan="100%">No data found</td></tr>';
            return;
        }

        const columns = Object.keys(rows[0]);

        this.elements.tableHead.innerHTML = '';
        const headerRow = document.createElement('tr');
        columns.forEach(column => {
            const th = document.createElement('th');
            th.textContent = column;
            headerRow.appendChild(th);
        });
        this.elements.tableHead.appendChild(headerRow);

        this.elements.tableBody.innerHTML = '';
        rows.forEach(row => {
            const tr = document.createElement('tr');
            columns.forEach(column => {
                const td = document.createElement('td');
                const value = row[column];

                if (value && typeof value === 'object' && value.type === 'vector') {
                    this.renderVectorCell(td, value, column);
                } else {
                    td.textContent = value === null ? 'null' : String(value);
                }

                tr.appendChild(td);
            });
            this.elements.tableBody.appendChild(tr);
        });

        this.elements.dataSection.style.display = 'block';
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
}

document.addEventListener('DOMContentLoaded', () => {
    new LanceViewer();
});