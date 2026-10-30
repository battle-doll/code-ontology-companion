"""Source-bound numeric contracts and conservative near-name controls."""
import unittest
from test_policy_java_contracts import extract, returns, bindings, expression_result


class NumericContractExtensionTests(unittest.TestCase):
    def contract(self, expression, method, parameters=None):
        result = expression_result(expression, **({"parameters": parameters} if parameters else {}))
        found = [c for row in returns(result) for _,c in bindings(row) if c['method']==method]
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]['executionSuccess'],'UNKNOWN')
        self.assertFalse(any(f['businessMeaningVerified'] for f in result['fragments']))
        return found[0]

    def test_remainder_to_sign_chain_retains_decimal_result(self):
        result = expression_result('n.remainder(d).signum()')
        pairs = {c['method']:c for _,c in bindings(returns(result)[0])}
        self.assertEqual(set(pairs),{'remainder','signum'})
        c=pairs['remainder']
        self.assertEqual(c['parameterTypes'],['java.math.BigDecimal'])
        self.assertEqual(c['rules']['integralQuotient'],'truncate_toward_zero')
        self.assertEqual(c['rules']['modulo'],'not_nonnegative_modulo')
        self.assertEqual(c['rules']['sign'],'may_be_negative')
        self.assertIn('zero_divisor',c['exceptionConditions']['java.lang.ArithmeticException'])
        self.assertIn('null_reference_argument',c['exceptionConditions']['java.lang.NullPointerException'])

    def test_context_precision_does_not_round_remainder(self):
        c=self.contract('n.remainder(d,mc)','remainder')
        self.assertEqual(c['parameterTypes'],['java.math.BigDecimal','java.math.MathContext'])
        self.assertEqual(c['rules']['rounding'],'exact_remainder')
        self.assertEqual(c['rules']['precisionScope'],'implicit_integral_quotient')
        self.assertTrue(c['rules']['remainderMayExceedContextPrecision'])
        self.assertIn('positive_precision_insufficient_for_integral_quotient',c['exceptionConditions']['java.lang.ArithmeticException'])

    def test_unproven_remainder_overload_stays_unknown(self):
        for expression in ['n.remainder(1)','n.remainder(d,rounding)','n.remainder(d,unknown)']:
            with self.subTest(expression=expression):
                self.assertFalse(any(c['method']=='remainder' for r in returns(expression_result(expression)) for _,c in bindings(r)))

    def test_custom_remainder_name_cannot_impersonate_platform(self):
        source='class Quantity { Quantity remainder(Quantity n){return this;} int signum(){return 1;} } class Rules { int f(Quantity n,Quantity d){return n.remainder(d).signum();}}'
        self.assertFalse(any(bindings(r) for r in returns(extract(source)[0])))

    def test_duration_nanosecond_subtraction_and_result_conversion(self):
        c=self.contract('duration.minusNanos(delta).toNanos()','minusNanos','Duration duration, long delta')
        self.assertEqual(c['parameterTypes'],['long'])
        self.assertEqual(c['rules']['unit'],'nanosecond')
        self.assertEqual(c['rules']['negativeAmount'],'add')
        self.assertEqual(c['rules']['receiverMutation'],'none')
        self.assertIn('duration_overflow',c['exceptionConditions']['java.lang.ArithmeticException'])

    def test_duration_int_widens_but_double_does_not(self):
        self.contract('duration.minusNanos(delta)','minusNanos','Duration duration, int delta')
        result=expression_result('duration.minusNanos(delta)',parameters='Duration duration, double delta')
        self.assertFalse(any(bindings(r) for r in returns(result)))

    def test_custom_duration_and_unknown_receiver_remain_unknown(self):
        for source in [
            'class Duration { Duration minusNanos(long n){return this;} } class Rules { Object f(Duration d,long n){return d.minusNanos(n);}}',
            'class Rules { Object f(Object d,long n){return d.minusNanos(n);}}']:
            with self.subTest(source=source): self.assertFalse(any(bindings(r) for r in returns(extract(source)[0])))


if __name__=='__main__': unittest.main()
