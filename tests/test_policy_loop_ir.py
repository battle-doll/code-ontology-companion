"""Neutral enhanced-for source structure, boundaries and opaque iteration data."""
import hashlib
import json
import unittest
from unittest import mock

from test_policy_java_contracts import extract, returns, bindings, pipeline_delivery, core, pipeline_java, policy_semantics
from test_policy_c5_syntax_review import extract_reviewed
from test_policy_literal_review import reviewed, occurrence, walk


def loops(result):
    return [f for f in result["fragments"] if (f.get("expression") or {}).get("op") == "enhanced_for"]


class EnhancedForSourceTests(unittest.TestCase):
    def test_declaration_iterable_and_inline_body_have_exact_source_binding(self):
        source = "record Piece(int count){} class CollectionCase{void f(Piece[] pieces){for(final Piece piece:pieces){use(piece);}}}"
        result, _ = extract(source); loop = loops(result)[0]; expr = loop["expression"]
        self.assertEqual(expr["variable"]["name"], "piece")
        self.assertEqual(expr["variable"]["declaredType"], "Piece")
        self.assertEqual(expr["iterable"]["name"], "pieces")
        for key, expected in (("variable", "final Piece piece"), ("body", "{use(piece);}")):
            span = expr[key]["sourceRange"]
            self.assertEqual(source[span["charStart"]:span["charEnd"]], expected)
        self.assertEqual(expr["body"]["sourceDigest"], hashlib.sha256(source.encode()).hexdigest())
        child = next(f for f in result["fragments"] if f.get("loopRelations"))
        context = child["controlFlow"]["contexts"][0]
        self.assertEqual(context["loopBodyId"], expr["body"]["id"])
        self.assertEqual(context["bodyDefinition"], {"fragmentId":loop["id"], "jsonPath":"expression.body"})
        self.assertEqual(expr["iteration"]["count"], "UNKNOWN")
        self.assertEqual(loop["representationStatus"], "partial")

    def test_ordered_array_iterable_preserves_opaque_unreviewed_terminals(self):
        source = 'class CollectionCase{void f(){for(String text:new String[]{"MODE_A","0.5","MODE_B"}){use(text);}}}'
        result, _ = extract(source); expr = loops(result)[0]["expression"]
        self.assertEqual(expr["iterable"]["op"], "array_construct")
        items = expr["iterable"]["initializer"]["elements"]
        self.assertEqual(len(items), 3)
        self.assertTrue(all(item["op"] == "redacted" for item in items))
        serialized = json.dumps(result)
        self.assertFalse(any(value in serialized for value in ("MODE_A", "MODE_B", "0.5")))
        self.assertEqual(expr["iteration"]["arrayElementOrder"], "source_initializer_order_only")

    def test_reviewed_array_literals_are_occurrence_bound_and_ordered(self):
        source = 'class CollectionCase{void f(){for(String text:new String[]{"MODE_A","MODE_B"}){use(text);}}}'
        result, review, _ = extract_reviewed(source, ['"MODE_A"','"MODE_B"'])
        items = loops(result)[0]["expression"]["iterable"]["initializer"]["elements"]
        self.assertEqual([item["value"] for item in items], ["MODE_A","MODE_B"])
        self.assertTrue(all("literalReview" in item for item in items))
        self.assertEqual(review.summary()["admittedEntries"], 2)
        self.assertEqual(result["coverage"]["literalReviewDelivery"]["retainedOccurrences"], 2)

    def test_sensitive_loop_header_and_deferred_body_mask_values_and_contracts(self):
        source = 'class CollectionCase{void f(){for(String secretText:new String[]{"MASK_SENTINEL"}){Runnable work=()->{use(81276345,"CHILD_SENTINEL");};}}}'
        result, review, _ = extract_reviewed(source, ['"MASK_SENTINEL"','"CHILD_SENTINEL"'])
        text = json.dumps(result)
        self.assertNotIn("MASK_SENTINEL", text); self.assertNotIn("CHILD_SENTINEL", text); self.assertNotIn("81276345", text)
        self.assertEqual(review.summary()["rejectedEntries"], 2)
        for fragment in result["fragments"]:
            if fragment.get("structuralOnly"):
                self.assertFalse(any("staticType" in n or "staticContract" in n for n in walk(fragment)))
        self.assertTrue(loops(result)[0]["structuralOnly"])

    def test_revoked_iterable_review_has_no_dangling_body_definition(self):
        source = 'class CollectionCase{void f(){for(String value:new String[]{"MODE"}){use(value);}}}'
        review, digest = reviewed(source,[occurrence(source,'"MODE"')])
        original_bind = review.bind_source
        def bind(*args, **kwargs):
            bound = original_bind(*args, **kwargs); admit = bound.admit
            def revoked(*a, **k):
                result = admit(*a, **k)
                if result["status"] == "admitted": review.reject(result["requestIndex"],"fragment_redacted")
                return result
            bound.admit = revoked
            return bound
        with mock.patch.object(review,"bind_source",side_effect=bind):
            result = policy_semantics.extract_semantics(source,"Java","Rules.java",digest,literal_review=review)
        self.assertFalse(loops(result))
        self.assertNotIn('"MODE"',json.dumps(result))
        self.assertFalse(any(f.get("loopRelations") for f in result["fragments"]))
        self.assertFalse(any("loopBodyId" in n for n in walk(result)))

    def test_guard_continue_break_and_accumulator_are_linked_without_value_proof(self):
        source = "import java.math.BigDecimal;record Piece(BigDecimal amount){}class CollectionCase{Object f(Piece[] pieces,BigDecimal total){for(Piece piece:pieces){if(piece.amount().signum()<0)continue;total=total.add(piece.amount());if(total.signum()>0)break;}return total;}}"
        result,_ = extract(source); loop = loops(result)[0]
        guards = [f for f in result["fragments"] if any(r["role"] == "iteration_guard" for r in f.get("loopRelations",[]))]
        self.assertEqual(len(guards),2)
        update = next(f for f in result["fragments"] if f.get("name") == "total")
        relation = update["loopRelations"][0]
        self.assertEqual(relation["role"],"accumulator_update_candidate")
        self.assertEqual(relation["reachingDefinitions"],"UNKNOWN")
        self.assertTrue(any(g["fragmentId"]==guards[0]["id"] and g["branch"]=="false" for g in relation["guardContexts"]))
        exits = [r for f in result["fragments"] for r in f.get("loopRelations",[]) if r["role"]=="abrupt_completion_syntax"]
        self.assertEqual({r["completionKind"] for r in exits},{"continue","break"})
        self.assertTrue(all(r["targetFragmentId"]==loop["id"] and r["runtimeTaken"]=="UNKNOWN" for r in exits))
        self.assertNotIn("loopRelations",returns(result)[-1])

    def test_nested_loop_and_switch_breaks_target_nearest_lexical_control(self):
        source = "class CollectionCase{void f(int[] outer,int[] inner){for(int left:outer){for(int right:inner){if(right>0)break;}switch(left){case 1:break;default:continue;}}}}"
        result,_=extract(source); outer,inner=loops(result)
        for fragment in result["fragments"]:
            expr=fragment.get("expression") or {}
            if expr.get("kind")=="break":
                relations=fragment["loopRelations"]
                if len(relations)==2:
                    self.assertTrue(all(r["targetFragmentId"]==inner["id"] for r in relations))
                else:
                    self.assertEqual(relations[0]["targetKind"],"switch")
            elif expr.get("kind")=="continue":
                self.assertEqual(fragment["loopRelations"][0]["targetFragmentId"],outer["id"])

    def test_deferred_lambda_anonymous_and_local_class_are_not_per_iteration_execution(self):
        source = "class CollectionCase{void f(int[] values){for(int value:values){Runnable run=()->{if(value>0)use(value);};Object object=new Object(){void later(){use(value);}};class Local{void later(){use(1);}}}}}"
        result,_=extract(source)
        deferred=[r for f in result["fragments"] for r in f.get("loopRelations",[]) if r["membership"]=="deferred_callable_source_nesting"]
        self.assertTrue(deferred)
        self.assertTrue(all(r["execution"]=="UNKNOWN" and r["role"]=="source_statement" for r in deferred))
        for fragment in result["fragments"]:
            if fragment.get("controlFlow",{}).get("owner",{}).get("name")=="later":
                self.assertTrue(all(r["membership"]=="deferred_callable_source_nesting" for r in fragment.get("loopRelations",[])))

    def test_labeled_abrupt_completion_is_not_given_guessed_target(self):
        source="class CollectionCase{void f(int[] values){done:for(int value:values){break done;}}}"
        result,_=extract(source)
        relation=next(r for f in result["fragments"] for r in f.get("loopRelations",[]) if r["role"]=="abrupt_completion_syntax")
        self.assertEqual(relation["targetResolution"],"UNKNOWN")
        self.assertNotIn("targetFragmentId",relation)

    def test_fragment_and_expression_budgets_stay_explicit(self):
        source='class CollectionCase{void f(){for(String value:new String[]{'+','.join('"X"' for _ in range(300))+'}){use(value);}}}'
        result,_=extract(source)
        loop=loops(result)[0]
        self.assertEqual(loop["expression"]["iterable"]["op"],"unresolved")
        self.assertIn("expression_budget_exceeded",loop["unsupportedReasons"])
        digest=hashlib.sha256(source.encode()).hexdigest()
        omitted=policy_semantics.extract_semantics(source,"Java","Rules.java",digest,max_fragments=1)
        self.assertFalse(omitted["coverage"]["inventoryComplete"])
        self.assertTrue(omitted["omissions"])
        self.assertLess(len(json.dumps(pipeline_delivery.normalize_response({"records":[loop]})).encode()),256*1024)

    def test_classic_for_remains_partial_and_has_no_enhanced_body_identity(self):
        result,_=extract("class CollectionCase{void f(){for(int i=0;i<10;i++){use(i);}}}")
        self.assertFalse(loops(result))
        header=next(f for f in result["fragments"] if (f.get("expression") or {}).get("op")=="loop_header")
        self.assertEqual(header["representationStatus"],"partial")


class ExactCustomReturnTests(unittest.TestCase):
    def test_unique_source_calls_with_arguments_and_nested_calls_already_compose(self):
        source="import java.math.BigDecimal;class AmountCase{String normalize(String text){return text;}BigDecimal parseAmount(String text){return BigDecimal.ZERO;}BigDecimal factor(){return BigDecimal.ONE;}BigDecimal minimum(){return BigDecimal.TEN;}Object f(String text){return parseAmount(normalize(text)).multiply(factor()).max(minimum());}}"
        row=returns(extract(source)[0])[-1]
        self.assertEqual({c["method"] for _,c in bindings(row)},{"multiply","max"})

    def test_unique_unqualified_source_call_in_loop_keeps_exact_return_evidence(self):
        source="import java.math.BigDecimal;record Piece(String text){}class AmountCase{BigDecimal parseAmount(String text){return BigDecimal.ZERO;}BigDecimal factor(){return BigDecimal.ONE;}Object f(Piece[] pieces){for(Piece piece:pieces){return parseAmount(piece.text()).multiply(factor());}return null;}}"
        row=returns(extract(source)[0])[-2]
        self.assertEqual({c["method"] for _,c in bindings(row)},{"multiply"})
        parsed=row["expression"]["callee"]["receiver"]
        self.assertEqual(parsed["staticType"]["basis"],"exact_source_call_return_declaration")
        self.assertEqual(parsed["staticType"]["evidenceKinds"],["callsite","symbol"])

    def test_overloaded_or_unknown_custom_call_in_loop_remains_unknown(self):
        source="import java.math.BigDecimal;record Piece(String text){}class AmountCase{BigDecimal parseAmount(String text){return BigDecimal.ZERO;}BigDecimal parseAmount(Object text){return BigDecimal.ONE;}Object f(Piece[] pieces){for(Piece piece:pieces){return parseAmount(piece.text()).abs();}return null;}}"
        self.assertFalse(bindings(returns(extract(source)[0])[-2]))


if __name__=="__main__": unittest.main()
