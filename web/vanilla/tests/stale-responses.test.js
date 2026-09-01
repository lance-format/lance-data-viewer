const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');


function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((resolvePromise, rejectPromise) => {
        resolve = resolvePromise;
        reject = rejectPromise;
    });
    return {promise, resolve, reject};
}


function loadViewer(fetchImpl) {
    const sourcePath = path.join(__dirname, '..', 'app.js');
    const source = `${fs.readFileSync(sourcePath, 'utf8')}\n`
        + 'globalThis.TestLanceViewer = LanceViewer;';
    const sandbox = {
        console,
        document: {addEventListener() {}},
        fetch: fetchImpl,
        URLSearchParams,
    };
    vm.createContext(sandbox);
    vm.runInContext(source, sandbox, {filename: sourcePath});
    return sandbox.TestLanceViewer;
}


function createViewer(Viewer) {
    const viewer = Object.create(Viewer.prototype);
    Object.assign(viewer, {
        apiBase: 'http://viewer.test',
        allColumns: [],
        currentDataset: 'first',
        currentPage: 0,
        dataRequestId: 0,
        datasetListRequestId: 0,
        metadataRequestId: 0,
        pageSize: 50,
        selectedColumns: [],
        totalRows: 0,
    });
    viewer.contextParams = () => new URLSearchParams();
    viewer.showLoading = () => {};
    return viewer;
}


test('a stale dataset-list response cannot replace a newer connection', async () => {
    const firstResponse = deferred();
    const secondResponse = deferred();
    const responses = [firstResponse.promise, secondResponse.promise];
    const Viewer = loadViewer(() => responses.shift());
    const viewer = createViewer(Viewer);
    const messages = [];
    const appended = [];
    const errors = [];

    viewer.elements = {
        datasetList: {
            appendChild: item => appended.push(item),
            replaceChildren() {},
        },
    };
    viewer.replaceWithMessage = (_element, message) => messages.push(message);
    viewer.showConnectionError = message => errors.push(message);

    const firstRequest = viewer.loadDatasets();
    const secondRequest = viewer.loadDatasets();

    secondResponse.resolve({
        ok: true,
        json: async () => ({datasets: []}),
    });
    assert.equal(await secondRequest, true);

    firstResponse.resolve({
        ok: true,
        json: async () => ({datasets: ['stale']}),
    });
    assert.equal(await firstRequest, false);

    assert.deepEqual(messages, [
        'Loading datasets...',
        'Loading datasets...',
        'No datasets found',
    ]);
    assert.deepEqual(appended, []);
    assert.deepEqual(errors, []);
});


test('a stale row response cannot replace a newer dataset', async () => {
    const firstResponse = deferred();
    const secondResponse = deferred();
    const responses = [firstResponse.promise, secondResponse.promise];
    const Viewer = loadViewer(() => responses.shift());
    const viewer = createViewer(Viewer);
    const rendered = [];
    const errors = [];
    let hiddenCount = 0;

    viewer.renderTable = rows => rendered.push(rows);
    viewer.updatePagination = () => {};
    viewer.hideLoading = () => { hiddenCount++; };
    viewer.showConnectionError = message => errors.push(message);
    viewer.showError = message => errors.push(message);

    const firstRequest = viewer.loadData();
    viewer.currentDataset = 'second';
    const secondRequest = viewer.loadData();

    secondResponse.resolve({
        ok: true,
        json: async () => ({rows: [{id: 'second'}], total: 1}),
    });
    await secondRequest;

    firstResponse.resolve({
        ok: true,
        json: async () => ({rows: [{id: 'first'}], total: 99}),
    });
    await firstRequest;

    assert.deepEqual(rendered, [[{id: 'second'}]]);
    assert.equal(viewer.totalRows, 1);
    assert.equal(hiddenCount, 1);
    assert.deepEqual(errors, []);
});


test('a stale row response cannot undo a newer column selection', async () => {
    const firstResponse = deferred();
    const secondResponse = deferred();
    const responses = [firstResponse.promise, secondResponse.promise];
    const Viewer = loadViewer(() => responses.shift());
    const viewer = createViewer(Viewer);
    const rendered = [];

    viewer.renderTable = rows => rendered.push(rows);
    viewer.updatePagination = () => {};
    viewer.hideLoading = () => {};
    viewer.showConnectionError = () => {};
    viewer.showError = () => {};

    const allColumnsRequest = viewer.loadData();
    viewer.allColumns = [{name: 'id'}, {name: 'text'}];
    viewer.selectedColumns = ['id'];
    const selectedColumnsRequest = viewer.loadData();

    secondResponse.resolve({
        ok: true,
        json: async () => ({rows: [{id: 1}], total: 1}),
    });
    await selectedColumnsRequest;

    firstResponse.resolve({
        ok: true,
        json: async () => ({rows: [{id: 1, text: 'stale'}], total: 1}),
    });
    await allColumnsRequest;

    assert.deepEqual(rendered, [[{id: 1}]]);
});


test('a stale metadata response cannot replace a newer dataset', async () => {
    const firstResponse = deferred();
    const secondResponse = deferred();
    const responses = [firstResponse.promise, secondResponse.promise];
    const Viewer = loadViewer(() => responses.shift());
    const viewer = createViewer(Viewer);
    const renderedSchemas = [];
    const renderedColumns = [];
    const errors = [];

    viewer.renderSchema = fields => renderedSchemas.push(fields);
    viewer.renderColumns = columns => renderedColumns.push(columns);
    viewer.showConnectionError = message => errors.push(message);
    viewer.showError = message => errors.push(message);

    const firstRequest = viewer.loadMetadata();
    viewer.currentDataset = 'second';
    const secondRequest = viewer.loadMetadata();

    secondResponse.resolve({
        ok: true,
        json: async () => ({fields: [{name: 'second'}], columns: [{name: 'second'}]}),
    });
    await secondRequest;

    firstResponse.resolve({
        ok: true,
        json: async () => ({fields: [{name: 'first'}], columns: [{name: 'first'}]}),
    });
    await firstRequest;

    assert.deepEqual(renderedSchemas, [[{name: 'second'}]]);
    assert.deepEqual(renderedColumns, [[{name: 'second'}]]);
    assert.deepEqual(errors, []);
});


test('a stale failed row request cannot replace the current error state', async () => {
    const firstResponse = deferred();
    const secondResponse = deferred();
    const responses = [firstResponse.promise, secondResponse.promise];
    const Viewer = loadViewer(() => responses.shift());
    const viewer = createViewer(Viewer);
    const errors = [];

    viewer.renderTable = () => {};
    viewer.updatePagination = () => {};
    viewer.hideLoading = () => {};
    viewer.showConnectionError = message => errors.push(message);
    viewer.showError = message => errors.push(message);

    const firstRequest = viewer.loadData();
    viewer.currentDataset = 'second';
    const secondRequest = viewer.loadData();

    secondResponse.resolve({
        ok: true,
        json: async () => ({rows: [], total: 0}),
    });
    await secondRequest;

    firstResponse.reject(new Error('old request failed'));
    await firstRequest;

    assert.deepEqual(errors, []);
});
