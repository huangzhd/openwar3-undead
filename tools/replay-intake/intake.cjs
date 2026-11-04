// Local, read-only W3G intake. A player name is not evidence of pro identity.
const fs = require('node:fs');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const zlib = require('node:zlib');

const SIGNATURE = Buffer.from('Warcraft III recorded game\x1a\0', 'ascii');
const MAX_FILE = 16 * 1024 * 1024;
const MAX_DATA = 64 * 1024 * 1024;
// Public decoder test inputs registered in docs/evidence/replay-intake-20261103.json.
const FORMAT_FIXTURES = new Set(['fbfa9e6ed9d1e97abce0fd5e524a9a1915f949ecf632766ae729807bd8e04e29']);
const hash = data => crypto.createHash('sha256').update(data).digest('hex');
function check(ok, message) { if (!ok) throw new Error(message); }

function header(bytes) {
  check(bytes.length >= 68 && bytes.length <= MAX_FILE && bytes.subarray(0,28).equals(SIGNATURE), 'invalid_w3g_envelope');
  const size = bytes.readUInt32LE(28);
  check(size === 68 && bytes.readUInt32LE(36) === 1, 'unsupported_header_layout');
  check(bytes.readUInt32LE(32) === bytes.length, 'declared_file_size_mismatch');
  const dataSize = bytes.readUInt32LE(40), blocks = bytes.readUInt32LE(44);
  check(dataSize > 0 && dataSize <= MAX_DATA && blocks > 0 && blocks <= MAX_DATA / 8192, 'invalid_data_budget');
  return { header_bytes:size, recorded_product:bytes.toString('ascii',48,52), version:bytes.readUInt32LE(52),
    build:bytes.readUInt16LE(56), header_duration_ms:bytes.readUInt32LE(60), declared_data_bytes:dataSize, blocks };
}

function inflateBlocks(bytes,h,modern) {
  check(h.blocks === Math.ceil(h.declared_data_bytes/8192), 'declared_block_count_mismatch');
  let pos=h.header_bytes;
  const data=Buffer.alloc(h.blocks*8192);
  for (let n=0; n<h.blocks; n++) {
    const blockHeader=modern?12:8;
    check(pos+blockHeader<=bytes.length, 'truncated_block_header');
    const length=modern?bytes.readUInt32LE(pos):bytes.readUInt16LE(pos);
    const expected=modern?bytes.readUInt32LE(pos+4):bytes.readUInt16LE(pos+2);
    pos+=blockHeader;
    check(length>0 && expected===8192 && pos+length<=bytes.length,'invalid_block_size');
    const decoded=zlib.inflateSync(bytes.subarray(pos,pos+length),{
      maxOutputLength:expected,finishFlush:zlib.constants.Z_SYNC_FLUSH,info:true
    });
    check(decoded.buffer.length===expected && decoded.engine.bytesWritten===length,'compressed_block_length_mismatch');
    decoded.buffer.copy(data,n*8192);
    pos+=length;
  }
  check(pos===bytes.length && data.subarray(h.declared_data_bytes).every(b=>b===0),'unexpected_block_padding');
  return data.subarray(0,h.declared_data_bytes);
}

// w3gjs can recover from an unknown action and return a partial list. Count
// actions only from an entire player block with exact consumption and no warning.
async function quiet(fn) {
  const saved=[console.log,console.warn,console.error];
  let warnings=0;
  console.log=console.warn=console.error=()=>{ warnings++; };
  try { return { value:await fn(),warnings }; }
  finally { [console.log,console.warn,console.error]=saved; }
}

const BUILD_CODES=['uaod','uzig','usep','utom','ugrv'];
const PROGRESSION_CODES={
  hero:['Udea','Ulic','Udre','Ucrl'],hall:['unp1','unp2'],
  skill:['AUdc','AUdp','AUau','AUan','AUfn','AUfu','AUdr','AUdd','AUav','AUsl','AUcs','AUin','AUim','AUts','AUcb','AUls']
};
const OPENING_MS=180000;
const MAX_DETAILS=512;

function recordBuild(opening,action,where,lastCode,lastPoint,subgroup) {
  if (!Array.isArray(action.orderId) || action.orderId.length!==4) return;
  const code=Buffer.from(action.orderId).reverse().toString('latin1');
  if (!BUILD_CODES.includes(code)) return;
  if (action.id!==0x11 || !Array.isArray(action.target) || action.target.length!==2 ||
      !action.target.every(Number.isFinite)) {
    opening.nonpoint_or_invalid_known_code++;return;
  }
  opening.observed_point_orders++;
  if (opening.orders.length>=MAX_DETAILS) {opening.omitted_over_limit++;return;}
  const point=action.target;
  const key=JSON.stringify([code,point]);
  const seq=opening.observed_point_orders;
  opening.orders.push({seq,...where,code,recorded_point:point,flags:action.abilityFlags,
    prior_subgroup:subgroup?{...subgroup,age_timeslot_ms:where.timeslot_ms-subgroup.timeslot_ms}:null,
    issue_actor_confirmed:false,
    prior_observed_same_code:lastCode.get(code)??null,prior_observed_exact_point:lastPoint.get(key)??null});
  lastCode.set(code,seq);lastPoint.set(key,seq);
}

async function inventory(gameData, humanIds, post202=false, openingPlayer=null,replayHash=null,progressionRequested=false,pressureRequested=false) {
  const { ActionParser }=require('w3gjs');
  const parser=new ActionParser(), players={}, other={blocks:0,undecoded_blocks:0};
  for (const id of humanIds) players[id]={blocks:0,decoded_blocks:0,undecoded_blocks:0,
    decoded_actions:0,orders_in_decoded_blocks:0,order_examples:[]};
  let pos=0, clock=0, timeslots=0, blocks=0;
  const lastCode=new Map(),lastPoint=new Map();
  let subgroup=null;
  const pressure=pressureRequested?require('./pressure.cjs').pressureCollector(openingPlayer,replayHash):null;
  const progression=progressionRequested?{schema:'dayuan-undead-progression-orders-v1',
    player_id:openingPlayer,covered_codes:PROGRESSION_CODES,orders:[],omitted_over_limit:0,
    engine_effects_verified:false}:null;
  const opening=openingPlayer===null?null:{schema:'dayuan-opening-orders-v2',player_id:openingPlayer,
    end_timeslot_ms:OPENING_MS,covered_codes:BUILD_CODES,observed_point_orders:0,
    nonpoint_or_invalid_known_code:0,omitted_over_limit:0,undecoded_blocks:0,gaps:[],orders:[]};
  function need(n,end=gameData.length) { check(n>=0 && pos+n<=end,'truncated_game_record'); }
  while (pos<gameData.length) {
    const tag=gameData[pos++];
    if (tag===0x1e || tag===0x1f) {
      need(2); const size=gameData.readUInt16LE(pos); pos+=2; need(size);
      const end=pos+size; need(2,end); clock+=gameData.readUInt16LE(pos); pos+=2; timeslots++;
      while (pos<end) {
        need(3,end); const id=gameData[pos],length=gameData.readUInt16LE(pos+1); pos+=3; need(length,end);
        const payloadOffset=pos,payload=gameData.subarray(pos,pos+length); pos+=length; blocks++;
        check(blocks<=500000,'too_many_command_blocks');
        const player=players[id] ?? other;
        player.blocks++;
        const parsed=await quiet(()=>parser.parse(payload,post202));
        const track=opening!==null && id===openingPlayer && clock<=OPENING_MS;
        if (parsed.warnings || parser.getOffset()!==length) {
          player.undecoded_blocks++;
          if(pressure && id===openingPlayer)pressure.gap({timeslot_ms:clock,block:blocks,payload_offset:payloadOffset,payload_bytes:length});
          if (track) {
            subgroup=null;
            opening.undecoded_blocks++;
            if (opening.gaps.length<MAX_DETAILS) opening.gaps.push({timeslot_ms:clock,block:blocks,
              payload_offset:payloadOffset,payload_bytes:length});
          }
          continue;
        }
        if (player===other) continue;
        player.decoded_blocks++; player.decoded_actions+=parsed.value.length;
        for (const [decodedIndex,action] of parsed.value.entries()) {
          if(pressure && id===openingPlayer)pressure.action(action,{timeslot_ms:clock,block:blocks,
            payload_offset:payloadOffset,payload_bytes:length,decoded_index:decodedIndex});
          if (progression && id===openingPlayer && action.id===0x10 && action.orderId?.length===4) {
            const code=Buffer.from(action.orderId).reverse().toString('latin1');
            const category=Object.keys(PROGRESSION_CODES).find(k=>PROGRESSION_CODES[k].includes(code));
            if (category) {
              if (progression.orders.length<MAX_DETAILS) progression.orders.push({timeslot_ms:clock,
                block:blocks,payload_offset:payloadOffset,payload_bytes:length,decoded_index:decodedIndex,
                category,code,flags:action.abilityFlags});
              else progression.omitted_over_limit++;
            }
          }
          if (track) {
            const where={timeslot_ms:clock,block:blocks,payload_offset:payloadOffset,payload_bytes:length,decoded_index:decodedIndex};
            if (action.id>=0x16 && action.id<=0x1b) {
              subgroup=null;
              if (action.id===0x19 && Array.isArray(action.itemId) && action.itemId.length===4 &&
                  Array.isArray(action.object) && action.object.length===2 &&
                  action.object.every(n=>Number.isInteger(n) && n>=0 && n<=0xffffffff) &&
                  !action.object.every(n=>n===0xffffffff)) {
                const type=Buffer.from(action.itemId).reverse().toString('latin1');
                if (/^[A-Za-z0-9]{4}$/.test(type))
                  subgroup={...where,type,replay_scoped_object:replayHash?
                    hash(JSON.stringify([replayHash,id,...action.object])).slice(0,24):null};
              }
            }
            recordBuild(opening,action,where,lastCode,lastPoint,subgroup);
          }
          if (!Array.isArray(action.orderId) || action.orderId.length!==4) continue;
          player.orders_in_decoded_blocks++;
          if (player.order_examples.length>=16) continue;
          const example={timeslot_ms:clock,action_id:action.id,order:Buffer.from(action.orderId).readUInt32LE()};
          if (Array.isArray(action.target) && action.target.length===2 && action.target.every(Number.isFinite))
            example.recorded_point=action.target;
          player.order_examples.push(example);
        }
      }
    } else {
      let length;
      if ([0x1a,0x1b,0x1c].includes(tag)) length=4;
      else if (tag===0x22) { need(1);length=1+gameData[pos]; }
      else if (tag===0x20) { need(3);length=3+gameData.readUInt16LE(pos+1); }
      else if (tag===0x17) length=13;
      else if (tag===0x23) length=10;
      else if (tag===0x2f) length=8;
      else throw new Error('unsupported_game_record_'+tag);
      need(length);pos+=length;
    }
  }
  if (opening) {
    opening.observed_until_ms=Math.min(clock,OPENING_MS);
    opening.omitted_gap_details=opening.undecoded_blocks-opening.gaps.length;
    opening.all_selected_blocks_decoded=opening.undecoded_blocks===0;
    opening.selection_and_visibility_verified=false;
    opening.construction_verified=false;
  }
  if (progression) {
    progression.observed_until_ms=clock;
    progression.undecoded_player_blocks=players[openingPlayer].undecoded_blocks;
  }
  return { timeslots, summed_timeslot_ms:clock,command_blocks:blocks,players,other_slots:other,
    ...(opening?{opening}:{}),...(progression?{progression}:{}),...(pressure?{pressure:pressure.report}:{}) };
}

async function inspect(bytes,includeNames=false,openingPlayer=null,progression=false,pressure=false) {
  check(!progression || openingPlayer!==null,'progression_requires_player');
  check(!pressure || openingPlayer!==null,'pressure_requires_player');
  const h=header(bytes), sha=hash(bytes);
  const result={schema:'dayuan-human-replay-intake-v1',sha256:sha,bytes:bytes.length,header:h,
    professional_identity:'unverified',map_binary_verified:false,player_view_reconstructed:false,
    engine_effects_verified:false,training_labels:0,positive_demonstrations_approved:false};
  const classic=(h.version===26 || h.version===27) && h.build===6059;
  const modern=h.version===10100 && h.build===6117;
  if (h.recorded_product!=='PX3W' || !(classic || modern)) {
    check(openingPlayer===null,'opening_requires_supported_replay');
    return {...result,status:'header_only',reason:'outside_tested_replay_profiles'};
  }
  const data=inflateBlocks(bytes,h,modern);
  const { MetadataParser }=require('w3gjs');
  const decoded=await quiet(()=>new MetadataParser().parseData(data));
  check(!decoded.warnings && (!classic || !decoded.value.isPost202ReplayFormat),'untrusted_replay_metadata');
  const m=decoded.value;
  check(m.slotRecords.length<=24 && m.playerRecords.length<=32,'invalid_player_metadata');
  const names=new Map();
  for (const record of m.playerRecords) {
    check(!names.has(record.playerId) || names.get(record.playerId)===record.playerName,'conflicting_replay_names');
    names.set(record.playerId,record.playerName);
  }
  const humanSlots=m.slotRecords.filter(s=>s.slotStatus===2 && s.computerFlag===0 && names.has(s.playerId));
  check(new Set(humanSlots.map(s=>s.playerId)).size===humanSlots.length,'duplicate_human_slot');
  result.human_slots=humanSlots.map(s=>{
    const name=names.get(s.playerId);
    const role=s.teamId===(h.version>=29?24:12)?'observer_or_referee':'participant';
    return {id:s.playerId,team:s.teamId,role,color:s.color,race_flag:s.raceFlag,
      replay_scoped_name_hash:hash(sha+'\0'+name),...(includeNames?{recorded_name:name}:{})};
  });
  result.map={replay_path:m.map.mapName,recorded_checksum:m.map.mapChecksum,
    recorded_checksum_sha1:m.map.mapChecksumSha1,always_visible:m.map.alwaysVisible,map_explored:m.map.mapExplored};
  if (openingPlayer!==null) check(result.human_slots.some(s=>s.id===openingPlayer && s.role==='participant'),
    'opening_player_not_a_participant');
  result.commands=await inventory(m.gameData,humanSlots.map(s=>s.playerId),m.isPost202ReplayFormat,openingPlayer,sha,progression,pressure);
  result.status=classic?'classic_command_inventory':'modern_command_inventory';
  result.post_202_action_format=m.isPost202ReplayFormat;
  result.command_scope='orders_in_fully_consumed_warning_free_player_blocks';
  result.all_command_blocks_decoded=result.commands.other_slots.undecoded_blocks===0 &&
    Object.values(result.commands.players).every(p=>p.undecoded_blocks===0);
  result.clock_delta_ms=result.commands.summed_timeslot_ms-h.header_duration_ms;
  return result;
}

function sourceRecord(s,report) {
  if (s===undefined) s={kind:FORMAT_FIXTURES.has(report.sha256)?'format_fixture':'local_reference'};
  check(s && typeof s==='object' && !Array.isArray(s),'invalid_source');
  const allowed=['kind','source_url','event','series','nominated_player_id','expected_sha256'];
  check(Object.keys(s).every(k=>allowed.includes(k)),'unknown_source_field');
  check(['local_reference','format_fixture','competition_candidate'].includes(s.kind),'invalid_source_kind');
  check(!FORMAT_FIXTURES.has(report.sha256) || s.kind==='format_fixture','known_format_fixture_source_mismatch');
  for (const k of ['source_url','event','series'])
    if (k in s) check(typeof s[k]==='string' && s[k].trim().length>0 && s[k].length<=1024
      && !/[\u0000-\u001f]/.test(s[k]),'invalid_source_text');
  if ('source_url' in s) {
    const u=new URL(s.source_url);
    check(['https:','http:'].includes(u.protocol) && !u.username && !u.password,'invalid_source_url');
  }
  if (s.kind==='competition_candidate')
    check(s.source_url && s.event && s.series && Number.isInteger(s.nominated_player_id),'competition_source_incomplete');
  if ('nominated_player_id' in s) {
    check(Number.isInteger(s.nominated_player_id) && s.nominated_player_id>=1 && s.nominated_player_id<=255,'invalid_nominated_player');
    if (report.human_slots) check(report.human_slots.some(x=>x.id===s.nominated_player_id && x.role==='participant'),
      'nominated_player_not_in_replay');
  }
  if ('expected_sha256' in s) check(typeof s.expected_sha256==='string' &&
    /^[0-9a-f]{64}$/.test(s.expected_sha256) && s.expected_sha256===report.sha256,'source_replay_hash_mismatch');
  return {...s,claim_verified:false,supplied_hash_matches:'expected_sha256' in s?true:null,
    nominated_slot_in_replay:('nominated_player_id' in s && report.human_slots)?true:null};
}

function readBounded(path,max) {
  const fd=fs.openSync(path,'r');
  try {
    const st=fs.fstatSync(fd);
    check(st.isFile() && st.size>0 && st.size<=max,'input_file_size_out_of_range');
    const bytes=Buffer.alloc(st.size);
    let offset=0;
    while (offset<bytes.length) {
      const n=fs.readSync(fd,bytes,offset,bytes.length-offset,null);
      check(n>0,'file_changed_during_read');offset+=n;
    }
    check(fs.fstatSync(fd).size===bytes.length,'file_changed_during_read');
    return bytes;
  } finally { fs.closeSync(fd); }
}

async function main(argv) {
  if (argv[0]==='--worker') {
    const bytes=fs.readFileSync(0);
    process.stdout.write(JSON.stringify(await inspect(bytes,argv[1]==='names',argv[2]?Number(argv[2]):null,argv[3]==='progression',argv[4]==='pressure')));
    return;
  }
  const {parseArgs}=require('node:util');
  const {values,positionals}=parseArgs({args:argv,allowPositionals:true,
    options:{out:{type:'string'},source:{type:'string'},names:{type:'boolean'},'opening-player':{type:'string'},
      'opening-review':{type:'boolean'},'review-notes':{type:'string'},progression:{type:'boolean'},pressure:{type:'boolean'}}});
  check(positionals.length===1 && values.out,'usage: node intake.cjs replay.w3g --out report.json [--source source.json] [--names] [--opening-player ID]');
  const openingPlayer=values['opening-player'];
  check(!values.pressure || (openingPlayer!==undefined && !values['opening-review']),'pressure_requires_player_inventory');
  check(!values.progression || (openingPlayer!==undefined && !values['opening-review']),'progression_requires_player_inventory');
  check(!values['opening-review'] || openingPlayer!==undefined,'review_requires_opening_player');
  check(values['review-notes']===undefined || values['opening-review'],'notes_require_opening_review');
  if (openingPlayer!==undefined) check(/^[1-9][0-9]{0,2}$/.test(openingPlayer) && Number(openingPlayer)<=255,'invalid_opening_player');
  const bytes=readBounded(positionals[0],MAX_FILE);
  const child=spawnSync(process.execPath,['--max-old-space-size=384',__filename,'--worker',values.names?'names':'private',openingPlayer??'',values.progression?'progression':'',values.pressure?'pressure':''],{
    input:bytes,encoding:'utf8',timeout:30000,maxBuffer:2*1024*1024,windowsHide:true});
  if (child.error) throw child.error;
  check(child.status===0,'replay_worker_failed: '+(child.stderr||'').slice(0,256));
  const report=JSON.parse(child.stdout);
  report.source=sourceRecord(values.source?JSON.parse(readBounded(values.source,16384).toString('utf8').replace(/^\uFEFF/,'')):
    undefined,report);
  if (openingPlayer && report.source.nominated_player_id!==undefined)
    check(report.source.nominated_player_id===Number(openingPlayer),'opening_player_differs_from_source');
  let output=report;
  if (values['opening-review']) {
    const notes=values['review-notes']===undefined?undefined:JSON.parse(
      readBounded(values['review-notes'],2*1024*1024).toString('utf8').replace(/^\uFEFF/,''));
    output=require('./opening-review.cjs').openingReview(report,notes);
  }
  fs.writeFileSync(values.out,JSON.stringify(output,null,2)+'\n',{flag:'wx',encoding:'utf8'});
  console.log(JSON.stringify({status:report.status,sha256:report.sha256,source_kind:report.source.kind,
    training_labels:report.training_labels,positive_demonstrations_approved:false}));
}

module.exports={inspect,inventory,sourceRecord};
if (require.main===module) main(process.argv.slice(2)).catch(e=>{console.error(e.message);process.exitCode=1;});
