"""Neutral unbraced enhanced-for boundaries, not runtime execution proof."""
import json
import unittest

from test_policy_java_contracts import core, pipeline_java, policy_semantics, extract, returns, bindings
from test_policy_literal_review import walk

PREFIX='class Outer{String read(){return null;}Entry[] entries(){return null;}}class Entry{java.math.BigDecimal read(){return null;}}class Event{boolean ready(){return true;}}'


def source(body,iterable='entries'):
    return PREFIX+'class Rules{Outer item;Entry[] entries;Event[] events;boolean active,other;Object gate;void f(){item.read();for(Entry item:'+iterable+')'+body+'item.read();}}'


def read_calls(text):
    return [c for c in core.build_java_index({'Rules.java':text}).calls['Rules.java'] if c['name']=='read']


class StatementExtentTests(unittest.TestCase):
    def test_compound_bodies_keep_binder_inside_and_outer_after(self):
        cases={
            'if':'if(active)item.read();',
            'if_else':'if(active)item.read();else item.read();',
            'nested_for':'for(Event event:events)item.read();',
            'nested_for_if':'for(Event event:events)if(event.ready())item.read();',
            'while':'while(active)item.read();',
            'do':'do item.read();while(active);',
            'do_if':'do if(active)item.read();else item.read();while(other);',
            'label':'retry:if(active)item.read();',
            'label_while':'retry:while(active)if(other)item.read();else break retry;',
            'synchronized':'synchronized(gate){item.read();}',
            'switch':'switch(1){case 1:item.read();break;default:item.read();}',
            'try':'try{item.read();}catch(RuntimeException problem){item.read();}finally{item.read();}',
            'resources':'try(AutoCloseable resource=acquire()){item.read();}',
            'dangling_else':'if(active)if(other)item.read();else item.read();',
            'if_for_else':'if(active)for(Event event:events)item.read();else item.read();',
            'empty_if':'if(active);else item.read();',
            'braced':'{item.read();}',
            'simple':'item.read();',
        }
        for name,body in cases.items():
            with self.subTest(shape=name):
                calls=read_calls(source(body))
                self.assertGreaterEqual(len(calls),3)
                self.assertEqual(calls[0]['target'],'java:method:Outer#read()')
                self.assertEqual(calls[-1]['target'],'java:method:Outer#read()')
                self.assertTrue(all(c.get('target')=='java:method:Entry#read()' for c in calls[1:-1]))
                self.assertTrue(all(c['runtimeDispatch']=='not_observed' for c in calls))

    def test_iterable_keeps_outer_receiver_and_nested_binders_are_distinct(self):
        text=source('for(Event event:events)if(event.ready())item.read();','item.entries()')
        calls=core.build_java_index({'Rules.java':text}).calls['Rules.java']
        self.assertEqual(next(c for c in calls if c['name']=='entries')['target'],'java:method:Outer#entries()')
        self.assertEqual(next(c for c in calls if c['name']=='ready')['target'],'java:method:Event#ready()')
        self.assertEqual([c['target'] for c in calls if c['name']=='read'],['java:method:Outer#read()','java:method:Entry#read()','java:method:Outer#read()'])

    def test_nested_offer_argument_and_receiver_are_both_inside_scope(self):
        text='class Event{}class Client{boolean offer(Event value){return true;}}class Outer{boolean offer(Event value){return false;}}class Rules{Outer client;Client[] clients;Event[] events;void f(Event input){client.offer(input);for(Client client:clients)for(Event event:events)if(!client.offer(event))break;client.offer(input);}}'
        calls=[c for c in core.build_java_index({'Rules.java':text}).calls['Rules.java'] if c['name']=='offer']
        self.assertEqual([c['target'] for c in calls],['java:method:Outer#offer(Event)','java:method:Client#offer(Event)','java:method:Outer#offer(Event)'])

    def test_sequential_loops_restore_outer_field_each_time(self):
        text=source('if(active)item.read();').replace('item.read();}}','item.read();for(Entry item:entries)while(active)item.read();item.read();}}')
        self.assertEqual([c['target'] for c in read_calls(text)],['java:method:Outer#read()','java:method:Entry#read()','java:method:Outer#read()','java:method:Entry#read()','java:method:Outer#read()'])

    def test_outer_local_restored_and_control_words_inside_literals_are_not_boundaries(self):
        text=source('consume("else } ; while(false)",item.read());').replace('void f(){','void f(){Outer item=null;')
        self.assertEqual([c['target'] for c in read_calls(text)],['java:method:Outer#read()','java:method:Entry#read()','java:method:Outer#read()'])
        text=source('if(active)consume(new Object(){void inside(){String s="else;";}},item.read());')
        self.assertEqual([c['target'] for c in read_calls(text)],['java:method:Outer#read()','java:method:Entry#read()','java:method:Outer#read()'])

    def test_missing_delimiters_and_depth_limit_remain_unknown(self):
        for body in ('do item.read();', 'if(active)item.read() else item.read();', 'if(active]'+'item.read();', 'if(active)'*40+'item.read();'):
            with self.subTest(body=body[:30]):
                calls=read_calls(source(body))
                self.assertEqual(calls[0]['target'],'java:method:Outer#read()')
                self.assertTrue(all(c['resolution']!='exact' for c in calls[1:]))

    def test_method_reference_and_identifier_suffix_are_not_labels_or_keywords(self):
        text=source('consume(item::read,thingelse(),item.read());')
        self.assertEqual([c['target'] for c in read_calls(text)],['java:method:Outer#read()','java:method:Entry#read()','java:method:Outer#read()'])

    def test_boundary_cache_does_not_share_across_methods(self):
        text=source('if(active)item.read();').replace('item.read();}}','item.read();}void g(){item.read();}}')
        self.assertEqual(read_calls(text)[-1]['target'],'java:method:Outer#read()')


class CompoundLoopSemanticTests(unittest.TestCase):
    def test_guard_update_and_body_links_remain_source_bound(self):
        text='import java.math.BigDecimal;record Reservation(BigDecimal amount){BigDecimal cash(){return amount;}}class Rules{boolean predicate(Reservation value){return true;}BigDecimal f(Reservation[] items,BigDecimal total){for(Reservation item:items)if(predicate(item))total=total.add(item.cash());return total;}}'
        result,facts=extract(text)
        loop=next(f for f in result['fragments'] if (f.get('expression')or{}).get('op')=='enhanced_for')
        body=loop['expression']['body'];span=body['sourceRange']
        self.assertEqual(text[span['charStart']:span['charEnd']],'if(predicate(item))total=total.add(item.cash());')
        self.assertEqual(loop['expression']['iterable']['name'],'items')
        guard=next(f for f in result['fragments'] if f.get('controlFlow',{}).get('kind')=='if')
        update=next(f for f in result['fragments'] if f.get('category')=='assignment')
        self.assertEqual(update['loopRelations'][0]['bodyId'],body['id'])
        self.assertEqual(update['loopRelations'][0]['role'],'accumulator_update_candidate')
        self.assertIn(guard['id'],[g['fragmentId'] for g in update['loopRelations'][0]['guardContexts']])
        self.assertEqual({c['method'] for _,c in bindings(update)},{'add'})
        self.assertFalse(result['coverage']['businessPolicyComplete'])
        self.assertEqual(loop['expression']['iteration']['count'],'UNKNOWN')
        self.assertFalse(returns(result)[-1].get('loopRelations'))

    def test_nested_unbraced_for_guard_and_break_have_two_real_body_definitions(self):
        text='class Event{}class Client{boolean offer(Event value){return true;}}class Rules{void f(Client[] clients,Event[] events){for(Client client:clients)for(Event event:events)if(!client.offer(event))break;}}'
        result,_=extract(text)
        loops=[f for f in result['fragments'] if (f.get('expression')or{}).get('op')=='enhanced_for']
        self.assertEqual(len(loops),2)
        stop=next(f for f in result['fragments'] if f.get('controlFlow',{}).get('kind')=='break')
        self.assertEqual({r['bodyId'] for r in stop['loopRelations']},{f['expression']['body']['id'] for f in loops})
        self.assertTrue(all(r['targetFragmentId']==loops[-1]['id'] for r in stop['loopRelations']))
        self.assertTrue(all(r['runtimeTaken']=='UNKNOWN' for r in stop['loopRelations']))
        self.assertTrue(all(r['guardContexts'] for r in stop['loopRelations']))

    def test_sensitive_unbraced_body_remains_masked_and_no_static_contract(self):
        text='record Reservation(java.math.BigDecimal amount){}class Rules{void f(Reservation[] values,boolean active){for(Reservation secretItem:values)if(active)consume(secretItem.amount().abs(),87162345,"MASK_SENTINEL");}}'
        result,_=extract(text)
        encoded=json.dumps(result)
        self.assertNotIn('87162345',encoded);self.assertNotIn('MASK_SENTINEL',encoded)
        self.assertFalse(any('staticContract' in node for node in walk(result)))
        self.assertTrue(any(f.get('structuralOnly') for f in result['fragments']))


if __name__=='__main__':unittest.main()
