const { test } = require('node:test');
const assert = require('node:assert/strict');
const { buildSync } = require('esbuild');
const vm = require('node:vm');
const output = buildSync({ entryPoints: ['src/api/adapter.ts'], bundle: true, platform: 'node', format: 'cjs', write: false }).outputFiles[0].text;
const context = { exports: {}, module: { exports: {} }, require }; context.exports = context.module.exports;
vm.runInNewContext(output, context); const adapter = context.module.exports;
test('raw scores remain aligned with backend thresholds', () => { for (const n of [0,40,59,60,79,80,100]) assert.equal(adapter.toTrustScore('human_review',n),n); });
test('reload retains notes, source pages, unverified fields and structured transactions', () => {
 const job = { applicant_id:'DEMO',submitted_at:'2026-01-01',overall:{risk_score:70,decision:'human_review',reasons:['Review']},documents:[{filename:'bank.pdf',document_type:'bank_statement',risk_score:70,decision:'human_review',reasons:[],field_verification:{status:'unverified',matched_fields:[]},extracted_fields:{pan:'TARPD4321E',transactions:[{credit:'70000'}]},page_assets:[{page_number:2,url:'/artifacts/page2.png'}]}],cross_document:[],reviewer_note:'Checked source',reconciliation:[] };
 const r=adapter.buildResultFromBatch(job,'http://localhost:8000'); assert.equal(r.documents[0].pipeline2.extracted_fields[0].status,'unverified'); assert.equal(r.documents[0].raw_fields.transactions[0].credit,'70000'); assert.equal(r.documents[0].page_assets[0].page_number,2); assert.equal(r.reviewer_note,'Checked source'); assert.equal('confidence' in r.overall,false);
});
