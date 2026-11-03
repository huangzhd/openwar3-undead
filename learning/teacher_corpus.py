"""Build or verify diagnostic teacher groups with explicit whole-episode splits."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from learning.dataset import canonical, digest, load_bytes, parse, require
from learning.teacher_dataset import audit_episode

SCHEMA='dayuan-teacher-corpus-v1'
SPLITS=('validation','train')  # Held-out groups are retained when exact inputs repeat.


def provenance(folder,report):
    b=load_bytes(folder,'interface-contract.json')
    require(digest(b)==report['input_hashes']['interface-contract.json'],'source_changed_during_audit')
    contract=parse(b)
    with (folder/'trajectory.jsonl').open('rb') as f:
        header=parse(f.readline(1<<20))
    return {k:contract[k] for k in ('source_manifest_sha256','map_sha256','policy','rules_version',
            'action_version','candidate_schema','observation_version','trajectory_schema','slots',
            'opponent','opponent_fairness','speed')} | dict(bounds=header['bounds'],
            dependencies_sha256=report['dependencies_sha256'],model_contract_sha256=report['model_contract']['sha256'])


def compile_splits(train, validation, stage=None):
    sets={'train':sorted(map(Path,train),key=lambda p:p.name), 'validation':sorted(map(Path,validation),key=lambda p:p.name)}
    require(all(sets.values()),'both_episode_splits_required')
    names=[p.resolve().name for split in SPLITS for p in sets[split]]
    require(len(names)==len(set(names)),'duplicate_episode_identity')
    group=None
    traces=set();examples_seen=set();heldout=set()
    index=dict(schema=SCHEMA,dataset_use='diagnostic_only',training_actor_approved=False,
               demonstration_source='rule_teacher',behavior_quality='unreviewed',positive_demonstrations_approved=False,
               split_method='explicit_whole_episode',exact_input_overlap='retain_validation_drop_train',
               episodes=[],splits={})
    for split in SPLITS:
        operations=Counter();variants=Counter();periods=Counter();seen=set();output_hash=hashlib.sha256()
        kept=partial=overlap=repeated=0
        stream=(stage/(split+'.jsonl')).open('xb') if stage else None
        try:
            for folder in sets[split]:
                report,groups=audit_episode(folder)
                require(bool(groups),'episode_has_no_labels')
                source=provenance(folder,report)
                if group is None:group=source
                require(source==group,'incompatible_episode_provenance')
                trace=report['input_hashes']['trajectory.jsonl']
                require(trace not in traces,'duplicate_trajectory')
                traces.add(trace)
                semantic=hashlib.sha256();retained=0
                for row in groups:
                    input_hash=digest(canonical(row['input']))
                    labels=[label['decision'] for label in row['labels']]
                    semantic.update(canonical([input_hash,labels,row['omitted_requests']])+b'\n')
                    if split=='train' and input_hash in heldout:
                        overlap+=1
                        continue
                    if input_hash in seen:repeated+=1
                    seen.add(input_hash)
                    kept+=1;retained+=1;partial+=int(row['omitted_requests']>0)
                    for label in labels:
                        vocab=report['model_contract']
                        op=vocab['operations'][label['op']]
                        operations[op]+=1
                        variant=op
                        for field,table in (('product','products'),('skill','skills'),('item','item_codes')):
                            if field in label:variant+=':'+vocab[table][label[field]]
                        if 'level' in label:variant+=':'+str(label['level'])
                        variants[variant]+=1
                    seconds=row['input']['clock']*3600
                    periods['under_300' if seconds<300 else '300_to_600' if seconds<600 else '600_plus']+=len(labels)
                    line=canonical(dict(episode=report['episode'],**row))+b'\n'
                    output_hash.update(line)
                    if stream:stream.write(line)
                fingerprint=semantic.hexdigest()
                require(fingerprint not in examples_seen,'duplicate_encoded_episode')
                examples_seen.add(fingerprint)
                index['episodes'].append(dict(episode=report['episode'],split=split,
                    trajectory_sha256=trace,example_sequence_sha256=fingerprint,
                    input_hashes=report['input_hashes'],termination=report['termination'],ticks=report['ticks'],
                    monitored_requests=report['monitored_requests'],source_labels=report['labels'],
                    source_groups=len(groups),retained_groups=retained,excluded_requests=report['excluded']))
                del groups
        finally:
            if stream:stream.close()
        require(kept>0,'no_disjoint_groups_in_split')
        if split=='validation':heldout=seen
        index['splits'][split]=dict(path=split+'.jsonl',sha256=output_hash.hexdigest(),groups=kept,
            partial_groups=partial,labels=sum(operations.values()),operations=dict(operations),
            action_variants=dict(variants),labels_by_game_seconds=dict(periods),unique_inputs=len(seen),within_split_repeat_groups=repeated,
            excluded_cross_split_groups=overlap)
    index['provenance']=group
    index['heldout_operations_absent_from_train']=sorted(set(index['splits']['validation']['operations'])
                                                         -set(index['splits']['train']['operations']))
    index['heldout_variants_absent_from_train']=sorted(set(index['splits']['validation']['action_variants'])
                                                      -set(index['splits']['train']['action_variants']))
    return index


def build(train,validation,out):
    out=Path(out)
    require(not out.exists(),'output_already_exists')
    out.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=out.parent) as tmp:
        stage=Path(tmp)
        index=compile_splits(train,validation,stage)
        (stage/'index.json').write_bytes(canonical(index)+b'\n')
        out.mkdir()  # Exclusive reservation. Publish index after the data files.
        moved=[]
        try:
            for name in ('validation.jsonl','train.jsonl','index.json'):
                (stage/name).rename(out/name)
                moved.append(out/name)
        except BaseException:
            for path in moved:path.unlink()
            out.rmdir()
            raise
    return index


def verify(train,validation,out):
    out=Path(out)
    expected=compile_splits(train,validation)
    require((out/'index.json').read_bytes()==canonical(expected)+b'\n','corpus_index_mismatch')
    for split in SPLITS:
        h=hashlib.sha256()
        with (out/(split+'.jsonl')).open('rb') as f:
            for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
        require(h.hexdigest()==expected['splits'][split]['sha256'],'corpus_data_mismatch')
    return expected


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('build','verify'))
    for name in ('train','validation'):parser.add_argument('--'+name,nargs='+',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    fn=build if args.operation=='build' else verify
    result=fn(args.train,args.validation,args.out)
    print(json.dumps(dict(operation=args.operation,splits=result['splits'],
          heldout_operations_absent_from_train=result['heldout_operations_absent_from_train'])))


if __name__=='__main__':main()
