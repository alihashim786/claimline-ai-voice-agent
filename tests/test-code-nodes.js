// Unit tests for the JavaScript inside the n8n Code nodes.
//
//   node tests/test-code-nodes.js
//
// The point: the Code nodes hold the only real logic in this project --
// ID repair, urgency triage, response shaping -- and testing them by
// making phone calls is slow, costs Retell credits, and tells you very
// little when it fails. This reads the actual jsCode out of the workflow
// JSON and runs it against a stub of n8n's runtime ($json, $input, $()),
// so a logic regression is caught in under a second without n8n, Google
// or Retell being involved at all.
//
// It reads n8n/*.json, so it tests exactly what you would import.

const fs = require('fs');
const wfA = JSON.parse(fs.readFileSync(
  __dirname + '/../n8n/workflow-a-mid-call-action-router.json', 'utf8'));
const wfB = JSON.parse(fs.readFileSync(
  __dirname + '/../n8n/workflow-b-post-call-confirmation.json', 'utf8'));

const codeOf = (wf, name) => wf.nodes.find(n => n.name === name).parameters.jsCode;

// Real rows from the Policies tab
const POLICIES = [
  { policy_number: 'POL-10234', holder_name: 'Sara Ahmed', coverage_type: 'Auto', valid_until: '2027-01-01' },
  { policy_number: 'POL-10567', holder_name: 'Bilal Riaz', coverage_type: 'Health', valid_until: '2026-11-15' },
  { policy_number: 'POL-11023', holder_name: 'Usman Tariq', coverage_type: 'Auto', valid_until: '2026-09-30' },
];
const CLAIMS = [
  { claim_id: 'CLM-000001', policy_number: 'POL-10234', holder_name: 'Sara Ahmed',
    incident_type: 'Accident', incident_date: '2026-08-04', urgency: 'Standard',
    status: 'Filed', created_at: '2026-08-06 14:03' },
];

function run(src, { json, all = [], nodes = {} }) {
  const $json = json;
  const $input = { all: () => all.map(j => ({ json: j })) };
  const $ = (name) => {
    if (!(name in nodes)) throw new Error('no stub for node ' + name);
    return { first: () => ({ json: nodes[name] }) };
  };
  return new Function('$json', '$input', '$', src)($json, $input, $);
}

let pass = 0, fail = 0;
function check(label, actual, expected) {
  const ok = String(actual) === String(expected);
  console.log(`  ${ok ? 'PASS' : 'FAIL'}  ${label}: ${actual}${ok ? '' : `  (expected ${expected})`}`);
  ok ? pass++ : fail++;
}

const NORM = codeOf(wfA, 'Normalize Request');
const norm = (args) => run(NORM, { json: { body: { args } } })[0].json;

console.log('\n--- Normalize Request -------------------------------------');
check('POL-10234 stays',        norm({ action: 'validate_policy', policy_number: 'POL-10234' }).policy_number, 'POL-10234');
check('"pol 10234" repaired',   norm({ action: 'validate_policy', policy_number: 'pol 10234' }).policy_number, 'POL-10234');
check('"10234" repaired',       norm({ action: 'validate_policy', policy_number: '10234' }).policy_number, 'POL-10234');
check('spoken "one 0 2 3 4"',   norm({ action: 'validate_policy', policy_number: 'P O L one 0 2 3 4' }).policy_number, 'POL-10234');
check('all words spoken',       norm({ action: 'validate_policy', policy_number: 'pol one zero two three four' }).policy_number, 'POL-10234');
check('"oh" for zero',          norm({ action: 'validate_policy', policy_number: 'P O L one oh two three four' }).policy_number, 'POL-10234');
check('prefix not eaten',       norm({ action: 'validate_policy', policy_number: 'POL-11023' }).policy_number, 'POL-11023');
check('spoken claim id',        norm({ action: 'check_status', claim_id: 'C L M zero zero zero zero four two' }).claim_id, 'CLM-000042');
check('claim 42 -> CLM-000042', norm({ action: 'check_status', claim_id: 'claim 42' }).claim_id, 'CLM-000042');
check('natural sentence',       norm({ action: 'validate_policy', policy_number: 'my policy number is POL-10234' }).policy_number, 'POL-10234');
check('spelled with dashes',    norm({ action: 'validate_policy', policy_number: 'P-O-L one zero two three four' }).policy_number, 'POL-10234');
check('empty input',            norm({ action: 'validate_policy', policy_number: '' }).policy_number, '');
check('action lowercased',      norm({ action: 'Validate_Policy' }).action, 'validate_policy');

const VAL = codeOf(wfA, 'Build Validate Response');
const validate = (pn) => run(VAL, {
  json: {}, all: POLICIES, nodes: { 'Normalize Request': { policy_number: pn } },
})[0].json;

console.log('\n--- Build Validate Response -------------------------------');
const v1 = validate('POL-10234');
check('valid policy result', v1.result, 'valid');
check('  holder_name',       v1.holder_name, 'Sara Ahmed');
check('  coverage_type',     v1.coverage_type, 'Auto');
check('unknown policy',      validate('POL-99999').result, 'not_found');
const expired = run(VAL, {
  json: {}, nodes: { 'Normalize Request': { policy_number: 'POL-00001' } },
  all: [{ policy_number: 'POL-00001', holder_name: 'Old Cust', coverage_type: 'Auto', valid_until: '2020-01-01' }],
})[0].json;
check('lapsed policy',       expired.result, 'expired');
check('empty sheet',         run(VAL, { json: {}, all: [{}], nodes: { 'Normalize Request': { policy_number: 'POL-10234' } } })[0].json.result, 'not_found');

const TRI = codeOf(wfA, 'Generate Claim ID & Triage');
const triage = (desc, hint = 'Standard', type = 'Accident') => run(TRI, {
  json: { policy_number: 'POL-10234', holder_name: 'Sara Ahmed', incident_type: type,
          incident_date: '2026-08-05', description: desc, email: 'a@b.com', urgency_hint: hint },
})[0].json;

console.log('\n--- Generate Claim ID & Triage ----------------------------');
const t1 = triage('Rear-ended at a signal, my wife was taken to hospital by ambulance');
check('hospital+ambulance -> Urgent', t1.urgency, 'Urgent');
check('  claim_id format',           /^CLM-\d{6}$/.test(t1.claim_id), 'true');
check('  created_at format',         /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/.test(t1.created_at), 'true');
check('  emits exactly 10 columns',  Object.keys(t1).length, 10);
check('  column names match sheet',
  Object.keys(t1).join(','),
  'claim_id,policy_number,holder_name,incident_type,incident_date,description,urgency,status,email,created_at');
check('bicycle theft -> Standard',   triage('My bicycle was stolen from outside the office', 'Standard', 'Theft').urgency, 'Standard');
check('fire -> Urgent',              triage('There was a fire in the kitchen').urgency, 'Urgent');
check('agent hint escalates',        triage('nothing notable here', 'Urgent').urgency, 'Urgent');
check('hint cannot downgrade',       triage('someone was taken to hospital', 'Standard').urgency, 'Urgent');

const STAT = codeOf(wfA, 'Build Status Response');
const status = (id) => run(STAT, {
  json: {}, all: CLAIMS, nodes: { 'Normalize Request': { claim_id: id } },
})[0].json;

console.log('\n--- Build Status Response ---------------------------------');
check('real claim found',  status('CLM-000001').result, 'found');
check('  status read back', status('CLM-000001').status, 'Filed');
check('fake claim',        status('CLM-999999').result, 'not_found');

const FLAT = codeOf(wfB, 'Flatten Retell Payload');
const flat = (cad) => run(FLAT, { json: { body: { event: 'call_analyzed',
  call: { call_id: 'c1', call_analysis: { custom_analysis_data: cad } } } } })[0].json;

console.log('\n--- Flatten Retell Payload --------------------------------');
check('boolean true',    flat({ claim_filed: true,  claim_id: 'CLM-1' }).claim_filed, 'true');
check('string "true"',   flat({ claim_filed: 'true' }).claim_filed, 'true');
check('boolean false',   flat({ claim_filed: false }).claim_filed, 'false');
check('missing field',   flat({}).claim_filed, 'false');
check('email lowercased', flat({ email: 'A@B.COM' }).email, 'a@b.com');
check('urgency defaults', flat({}).urgency, 'n/a');

const AR = codeOf(wfB, 'Analytics Row — Filed');
const arow = run(AR, { json: { id: 'gmail-response' },
  nodes: { 'Flatten Retell Payload': { timestamp: '2026-08-06 14:03', urgency: 'Urgent', incident_type: 'Accident' } } })[0].json;
console.log('\n--- Analytics Row — Filed ---------------------------------');
check('reads Flatten not $json', arow.urgency, 'Urgent');
check('exactly 4 columns',       Object.keys(arow).join(','), 'timestamp,claim_filed,urgency,incident_type');

console.log(`\n=========================================\n  Passed: ${pass}   Failed: ${fail}\n=========================================`);
process.exit(fail ? 1 : 0);
