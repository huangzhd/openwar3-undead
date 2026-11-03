const {test}=require('node:test');
const assert=require('node:assert/strict');
const zlib=require('node:zlib');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {spawnSync}=require('node:child_process');
const {inspect,inventory,sourceRecord}=require('./intake.cjs');
const {openingReview}=require('./opening-review.cjs');

function envelope(raw,{build=6059,declared=raw.length,padding=0}={}) {
  const block=Buffer.alloc(8192,padding); raw.copy(block);
  const compressed=zlib.deflateSync(block);
  const header=Buffer.alloc(68);
  Buffer.from('Warcraft III recorded game\x1a\0').copy(header);
  header.writeUInt32LE(68,28); header.writeUInt32LE(76+compressed.length,32);
  header.writeUInt32LE(1,36); header.writeUInt32LE(declared,40); header.writeUInt32LE(1,44);
  header.write('PX3W',48);header.writeUInt32LE(27,52);header.writeUInt16LE(build,56);
  const sizes=Buffer.alloc(8);sizes.writeUInt16LE(compressed.length);sizes.writeUInt16LE(8192,2);
  return Buffer.concat([header,sizes,compressed]);
}
function timeslot(blocks,increment=10) {
  const time=Buffer.alloc(2);time.writeUInt16LE(increment);
  const parts=[time];
  for (const [id,actions] of blocks) {
    const prefix=Buffer.alloc(3);prefix[0]=id;prefix.writeUInt16LE(actions.length,1);
    parts.push(prefix,Buffer.from(actions));
  }
  const bytes=Buffer.concat(parts);const head=Buffer.alloc(3);head[0]=0x1f;head.writeUInt16LE(bytes.length,1);
  return Buffer.concat([head,bytes]);
}

function buildOrder(code,x,y) {
  const order=Buffer.alloc(23);
  order[0]=0x11;Buffer.from(code,'ascii').reverse().copy(order,3);
  order.writeFloatLE(x,15);order.writeFloatLE(y,19);
  return order;
}

test('opening chronology keeps same-point repeats, changed sites and missing blocks for only the selected slot',async()=>{
  const a=buildOrder('uaod',-3616,-3360),b=buildOrder('uaod',-3552,-3296);
  const data=Buffer.concat([timeslot([[1,a],[2,buildOrder('uzig',128,64)]],5000),
    timeslot([[1,Buffer.concat([a,Buffer.from([255])])]],500),
    timeslot([[1,Buffer.concat([a,b])]],500)]);
  const result=(await inventory(data,[1,2],false,1)).opening;
  assert.deepEqual(result.orders.map(r=>[r.timeslot_ms,r.code,r.prior_observed_same_code,r.prior_observed_exact_point]),
    [[5000,'uaod',null,null],[6000,'uaod',1,1],[6000,'uaod',2,null]]);
  assert.equal(result.gaps.length,1);
  assert.equal(result.gaps[0].timeslot_ms,5500);
  assert.equal(result.all_selected_blocks_decoded,false);
  assert.equal(result.construction_verified,false);
  for (const r of result.orders) assert.equal(data[r.payload_offset+r.decoded_index*a.length],0x11);
});

test('opening includes the exact time boundary, ignores unknown products, and counts over-limit detail',async()=>{
  const a=buildOrder('usep',32,64), unknown=buildOrder('hbar',32,64);
  const data=Buffer.concat([timeslot([],60000),timeslot([],60000),
    timeslot([[1,Buffer.concat([unknown,...Array(514).fill(a)])]],60000),timeslot([[1,a]],1)]);
  const result=(await inventory(data,[1],false,1)).opening;
  assert.equal(result.observed_point_orders,514);
  assert.equal(result.orders.length,512);
  assert.equal(result.omitted_over_limit,2);
  assert.equal(result.orders[511].prior_observed_exact_point,511);
  assert.equal(result.observed_until_ms,180000);
});

test('subgroup evidence stays player-local, expires on selection changes or gaps, and never assigns an actor',async()=>{
  function subgroup(code,n) {
    const b=Buffer.alloc(13);b[0]=0x19;Buffer.from(code).reverse().copy(b,1);
    b.writeUInt32LE(n,5);b.writeUInt32LE(32,9);return b;
  }
  const a=buildOrder('uzig',32,32);
  const data=Buffer.concat([timeslot([[1,subgroup('uaco',45)],[2,subgroup('Hpal',46)]]),
    timeslot([[1,a],[1,Buffer.concat([subgroup('hmil',49),a])]]),
    timeslot([[1,Buffer.from([255])],[1,a]]),
    timeslot([[1,Buffer.concat([subgroup('uaco',45),Buffer.from([0x18,0,0]),a])]])]);
  const r=(await inventory(data,[1,2],false,1,'a'.repeat(64))).opening.orders;
  assert.deepEqual(r.map(x=>x.prior_subgroup?.type??null),['uaco','hmil',null,null]);
  assert.equal(r[0].prior_subgroup.age_timeslot_ms,10);
  assert.notEqual(r[0].prior_subgroup.replay_scoped_object,r[1].prior_subgroup.replay_scoped_object);
  assert.ok(r.every(x=>x.issue_actor_confirmed===false));
});

test('unknown versions remain header-only and cannot claim player-view or professional status',async()=>{
  const report=await inspect(envelope(Buffer.from('placeholder'),{build:7000}));
  assert.equal(report.status,'header_only');
  assert.equal(report.player_view_reconstructed,false);
  assert.equal(report.professional_identity,'unverified');
  assert.equal(report.commands,undefined);
});

test('file and decompressed boundaries are checked before reading any metadata',async()=>{
  const bytes=envelope(Buffer.from('x'));
  await assert.rejects(()=>inspect(bytes.subarray(0,-1)),/file_size/);
  const oversized=Buffer.from(bytes);oversized.writeUInt32LE(65*1024*1024,40);
  await assert.rejects(()=>inspect(oversized),/budget/);
  await assert.rejects(()=>inspect(envelope(Buffer.from('x'),{padding:1})),/padding/);
  const trailing=Buffer.concat([bytes,Buffer.from([12])]);trailing.writeUInt32LE(trailing.length,32);
  await assert.rejects(()=>inspect(trailing),/padding/);
});

test('a malformed player block cannot donate partial order hints or corrupt the next slot',async()=>{
  // 0x10 immediate command: flags, order id, two unknown uint32 arguments.
  const order=[0x10,0,0,3,0,13,0,0,0,0,0,0,0,0,0];
  const d=await inventory(timeslot([[1,[...order,0xff]],[2,order],[3,[0xff]]]),[1,2]);
  assert.equal(d.players[1].undecoded_blocks,1);
  assert.equal(d.players[1].orders_in_decoded_blocks,0);
  assert.equal(d.players[2].orders_in_decoded_blocks,1);
  assert.equal(d.players[2].order_examples[0].order,851971);
  assert.equal(d.players[2].order_examples[0].timeslot_ms,10);
  assert.equal(d.other_slots.undecoded_blocks,1);
});

test('unrecognized framing never resumes at a guessed offset',async()=>{
  await assert.rejects(()=>inventory(Buffer.from([0xff,0x1f,2,0,0,0]),[1]),/unsupported_game_record/);
  await assert.rejects(()=>inventory(timeslot([[1,[1,2,3]]]).subarray(0,-1),[1]),/truncated/);
});

test('a source claim must bind to an actual slot and optional pinned file hash',()=>{
  const report={sha256:'a'.repeat(64),human_slots:[{id:2,role:'participant'},{id:3,role:'observer_or_referee'}]};
  const source={kind:'competition_candidate',event:'Example Cup',series:'Final',
    source_url:'https://example.org/bracket',nominated_player_id:2,expected_sha256:report.sha256};
  const result=sourceRecord(source,report);
  assert.equal(result.claim_verified,false);assert.equal(result.nominated_slot_in_replay,true);
  assert.throws(()=>sourceRecord({...source,nominated_player_id:1},report),/not_in_replay/);
  assert.throws(()=>sourceRecord({...source,nominated_player_id:3},report),/not_in_replay/);
  assert.throws(()=>sourceRecord({...source,expected_sha256:'b'.repeat(64)},report),/hash_mismatch/);
  assert.throws(()=>sourceRecord({...source,pro_verified:true},report),/unknown_source_field/);
  assert.throws(()=>sourceRecord({...source,source_url:'file:///tmp/match'},report),/source_url/);
});

test('CLI reads a pinned input locally and never replaces an existing result',t=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'dayuan-w3g-'));
  t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  const input=path.join(dir,'sample.w3g'),out=path.join(dir,'report.json');
  const bytes=envelope(Buffer.from('metadata unavailable'),{build:7000});
  fs.writeFileSync(input,bytes);
  const args=[path.join(__dirname,'intake.cjs'),input,'--out',out];
  assert.equal(spawnSync(process.execPath,args,{encoding:'utf8'}).status,0);
  const saved=fs.readFileSync(out);
  assert.equal(JSON.parse(saved).source.kind,'local_reference');
  assert.notEqual(spawnSync(process.execPath,args,{encoding:'utf8'}).status,0);
  assert.deepEqual(fs.readFileSync(out),saved);
  assert.deepEqual(fs.readFileSync(input),bytes);
});

test('review keeps repeat, site changes and unavailable observations separate from verdicts',async()=>{
  const a=buildOrder('uaod',32,64),b=buildOrder('uaod',64,64);
  const commands=await inventory(timeslot([[1,Buffer.concat([a,b,a])],[1,[255]]]),[1],false,1);
  const report={sha256:'a'.repeat(64),source:{kind:'local_reference'},commands};
  const sheet=openingReview(report);
  assert.deepEqual(sheet.rows[2].signals,['previous_order_at_same_site','different_site_from_previous_same_building','no_typed_subgroup']);
  assert.equal(sheet.coverage.undecoded_blocks,1);
  assert.ok(sheet.rows.every(r=>r.annotation===null));
  const note={id:sheet.rows[2].id,verdict:'possible_reissue_or_correction',comment:'Check the two distinct sites.'};
  const reviewed=openingReview(report,[note]);
  assert.equal(reviewed.rows[2].annotation.comment,note.comment);
  assert.equal(reviewed.training_labels,0);
  assert.throws(()=>openingReview(report,[note,note]),/duplicate/);
  assert.throws(()=>openingReview(report,[{...note,approved:true}]),/invalid_review_annotation/);
  for (const mutate of [
    r=>r.sha256='b'.repeat(64),r=>r.source.kind='competition_candidate',r=>r.commands.opening.player_id=2,
    r=>r.commands.opening.orders[2].recorded_point[0]++,r=>r.commands.opening.orders[2].timeslot_ms++,
    r=>r.commands.opening.orders[2].block++
  ]) {
    const changed=structuredClone(report);
    mutate(changed);
    assert.throws(()=>openingReview(changed,[note]),/unmatched/);
  }
});

test('registered parser fixture keeps its role even when renamed or supplied without a source',async()=>{
  const report={sha256:'fbfa9e6ed9d1e97abce0fd5e524a9a1915f949ecf632766ae729807bd8e04e29',
    commands:await inventory(timeslot([[1,buildOrder('uzig',32,64)]]),[1],false,1)};
  report.source=sourceRecord(undefined,report);
  assert.equal(report.source.kind,'format_fixture');
  for (const kind of ['local_reference','competition_candidate'])
    assert.throws(()=>sourceRecord({kind},report),/known_format_fixture/);
  const [{id}]=openingReview(report).rows;
  assert.throws(()=>openingReview(report,[{id,verdict:'tactical_review_candidate',comment:'Unverified'}]),/format_review_only/);
});

test('progression retains later player-local immediate orders and excludes damaged blocks and targeted casts',async()=>{
  function now(code) {
    const order=Buffer.alloc(15);
    order[0]=0x10;Buffer.from(code).reverse().copy(order,3);
    return order;
  }
  const data=Buffer.concat([timeslot([[2,now('Udre')],[1,now('Udea')]],60000),
    timeslot([[1,Buffer.concat([now('unp2'),Buffer.from([255])])]],60000),
    timeslot([[1,buildOrder('AUdc',32,64)]],60000),
    timeslot([[1,Buffer.concat([now('AUdc'),now('unp1'),now('unp1')])]],4000)]);
  const result=(await inventory(data,[1,2],false,1,null,true)).progression;
  assert.deepEqual(result.orders.map(o=>[o.timeslot_ms,o.category,o.code]),
    [[60000,'hero','Udea'],[184000,'skill','AUdc'],[184000,'hall','unp1'],[184000,'hall','unp1']]);
  assert.equal(result.undecoded_player_blocks,1);
  assert.equal(result.engine_effects_verified,false);
});
