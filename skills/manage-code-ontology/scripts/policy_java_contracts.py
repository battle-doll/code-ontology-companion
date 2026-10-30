"""Bounded Java SE API contracts, independent of application vocabulary.

Only resolved static operand types select a documented overload. These are
declaration-level contracts, never execution, value, dispatch or policy proofs.
The original expression and its unresolved runtime reasons remain intact.
"""
from __future__ import annotations

if "policy_java_platform" not in globals():
    import code_ontology_core
    policy_java_platform = code_ontology_core._load_bundled_helper("policy_java_platform")

import hashlib
import json

BD = "java.math.BigDecimal"
MC = "java.math.MathContext"
RM = "java.math.RoundingMode"
MATH = "java.lang.Math"
DURATION = "java.time.Duration"
INSTANT = "java.time.Instant"
TEMPORAL = "java.time.temporal.Temporal"
TIME_UNIT = "java.util.concurrent.TimeUnit"
SYSTEM = "java.lang.System"
FUTURE = "java.util.concurrent.CompletableFuture"
FUNCTION = "java.util.function.Function"
BICONSUMER = "java.util.function.BiConsumer"
COMPARATOR = "java.util.Comparator"
RESPONSE = "org.springframework.http.ResponseEntity"
BODY = RESPONSE + ".BodyBuilder"
HEADERS = RESPONSE + ".HeadersBuilder"
STATUS = "org.springframework.http.HttpStatusCode"
SPRING_DOC = "https://docs.spring.io/spring-framework/docs/6.2.12/javadoc-api/org/springframework/http/"
KEY_FUNCTIONS = {"Int": "java.util.function.ToIntFunction", "Long": "java.util.function.ToLongFunction", "Double": "java.util.function.ToDoubleFunction", "": FUNCTION}
VERSION = "java-se21-static-contracts-1"
DOC_ROOT = "https://docs.oracle.com/en/java/javase/21/docs/api/java.base/"
ROUNDINGS = {"UP", "DOWN", "CEILING", "FLOOR", "HALF_UP", "HALF_DOWN", "HALF_EVEN", "UNNECESSARY"}
ROUNDING_RULES = {"UP": "away_from_zero", "DOWN": "toward_zero", "CEILING": "toward_positive_infinity",
                  "FLOOR": "toward_negative_infinity", "HALF_UP": "nearest_ties_away_from_zero",
                  "HALF_DOWN": "nearest_ties_toward_zero", "HALF_EVEN": "nearest_ties_even",
                  "UNNECESSARY": "exact_or_arithmetic_exception"}
NUMERIC = ("byte", "short", "char", "int", "long", "float", "double")
WIDEN = {"byte": ("short", "int", "long", "float", "double"), "short": ("int", "long", "float", "double"),
         "char": ("int", "long", "float", "double"), "int": ("long", "float", "double"),
         "long": ("float", "double"), "float": ("double",)}
TIME_UNITS = {"NANOSECONDS": 1, "MICROSECONDS": 1000, "MILLISECONDS": 1000000, "SECONDS": 1000000000,
              "MINUTES": 60000000000, "HOURS": 3600000000000, "DAYS": 86400000000000}


def _comparable_types():
    entries = []
    for name, order, equals in (("java.lang.String", "utf16_lexicographic", "not_inferred"),
            (BD, "numeric_ignoring_scale", "may_differ_from_equals"), (INSTANT, "timeline_position", "not_inferred"),
            ("java.lang.Integer", "signed_integer_numeric", "not_inferred"), ("java.lang.Long", "signed_long_numeric", "not_inferred"),
            ("java.lang.Double", "double_total_order_nan_after_infinity_negative_zero_before_positive_zero", "not_inferred")):
        value = {"schemaVersion":1, "catalogVersion":"jdk21-comparable-self-1", "qualifiedName":name,
            "comparableTypeArgument":name, "relation":"documented_Comparable_of_exact_self", "orderRule":order,
            "comparisonEquality":"compareTo_result_zero", "objectEquality":equals, "referenceJdk":"Java SE 21",
            "actualTargetJdk":"UNKNOWN", "specification":DOC_ROOT+name.replace(".","/")+".html#compareTo("+name+")"}
        entries.append({"id":"jdk21-comparable:"+hashlib.sha256(policy_java_platform.canonical(value)).hexdigest()[:24], **value})
    return entries


COMPARABLE_TYPES = _comparable_types()


def _registry():
    result = {}

    def add(owner, name, parameters, returns, operation, *, static=False, **rules):
        result.setdefault((owner, name, static), []).append({"parameters": list(parameters), "returnType": returns,
            "operation": operation, "rules": rules})

    for name in ("add", "subtract", "multiply"):
        scale = "sum_operand_scales" if name == "multiply" else "maximum_operand_scale"
        add(BD, name, (BD,), BD, "decimal_" + name, scale=scale, rounding="exact")
        add(BD, name, (BD, MC), BD, "decimal_" + name, precisionArgument=1, rounding="math_context",
            exceptions={"java.lang.ArithmeticException": ["inexact_and_rounding_unnecessary"]})
    add(BD, "divide", (BD,), BD, "decimal_divide", preferredScale="receiver_scale_minus_divisor_scale", rounding="exact",
        exceptions={"java.lang.ArithmeticException": ["zero_divisor", "nonterminating_decimal_quotient"]})
    add(BD, "divide", (BD, MC), BD, "decimal_divide", precisionArgument=1, rounding="math_context",
        exceptions={"java.lang.ArithmeticException": ["zero_divisor", "inexact_and_rounding_unnecessary", "zero_precision_and_nonterminating_quotient"]})
    # Remainder uses the integer quotient, not a nonnegative modulo operation.
    # A context constrains the implicit quotient; the remainder itself is exact.
    for parameters in ((BD,), (BD, MC)):
        rules = dict(formula="receiver_minus_integral_quotient_times_divisor",
                     integralQuotient="truncate_toward_zero", rounding="exact_remainder",
                     sign="may_be_negative", modulo="not_nonnegative_modulo")
        errors = ["zero_divisor", "possible_scale_overflow_or_underflow"]
        if len(parameters) == 2:
            rules.update(precisionArgument=1, precisionScope="implicit_integral_quotient",
                         remainderMayExceedContextPrecision=True)
            errors.extend(["inexact_and_rounding_unnecessary", "positive_precision_insufficient_for_integral_quotient"])
        add(BD, "remainder", parameters, BD, "decimal_remainder",
            exceptions={"java.lang.ArithmeticException": errors}, **rules)
    for rounding in (RM, "int"):
        for explicit_scale in (False, True):
            params = (BD, "int", rounding) if explicit_scale else (BD, rounding)
            rules = {"scaleArgument": 1} if explicit_scale else {"scale": "receiver_scale"}
            errors = {"java.lang.ArithmeticException": ["zero_divisor", "inexact_and_rounding_unnecessary"]}
            if rounding == "int": errors["java.lang.IllegalArgumentException"] = ["invalid_legacy_rounding_mode"]
            add(BD, "divide", params, BD, "decimal_divide", rounding="argument", roundingArgument=len(params)-1,
                legacyRounding=rounding == "int", exceptions=errors, **rules)
        errors = {"java.lang.ArithmeticException": ["inexact_and_rounding_unnecessary"]}
        if rounding == "int": errors["java.lang.IllegalArgumentException"] = ["invalid_legacy_rounding_mode"]
        add(BD, "setScale", ("int", rounding), BD, "decimal_rescale", scaleArgument=0, rounding="argument", roundingArgument=1,
            legacyRounding=rounding == "int", exceptions=errors)
    add(BD, "setScale", ("int",), BD, "decimal_rescale", scaleArgument=0, rounding="exact",
        exceptions={"java.lang.ArithmeticException": ["rounding_required"]})
    for name in ("abs", "negate"):
        add(BD, name, (), BD, "decimal_" + name, scale="receiver_scale", rounding="exact")
        add(BD, name, (MC,), BD, "decimal_" + name, precisionArgument=0, rounding="math_context",
            exceptions={"java.lang.ArithmeticException": ["inexact_and_rounding_unnecessary"]})
    for name in ("min", "max"):
        add(BD, name, (BD,), BD, "decimal_" + name, comparison="numeric_ignores_scale", tie="receiver")
    add(BD, "compareTo", (BD,), "int", "decimal_compare", outcomes={"less": -1, "equal": 0, "greater": 1}, comparison="numeric_ignores_scale")
    add(BD, "signum", (), "int", "decimal_sign", outcomes={"negative": -1, "zero": 0, "positive": 1})
    add(BD, "scale", (), "int", "decimal_scale")
    add(BD, "valueOf", ("long",), BD, "decimal_from_integer", static=True, scale=0)
    add(BD, "valueOf", ("long", "int"), BD, "decimal_from_unscaled_integer", static=True, scaleArgument=1)
    add(BD, "valueOf", ("double",), BD, "decimal_from_canonical_double_string", static=True,
        exceptions={"java.lang.NumberFormatException": ["nonfinite_argument"]})

    for primitive in ("int", "long", "float", "double"):
        floating = primitive in {"float", "double"}
        for name in ("min", "max"):
            rules = {"floatingSpecialCases": "nan_propagates_signed_zero_ordered"} if floating else {}
            add(MATH, name, (primitive, primitive), primitive, "numeric_" + name, static=True, **rules)
        rules = {"floatingSpecialCases": "nan_and_positive_zero_absolute"} if floating else {"overflow": "minimum_integer_unchanged"}
        add(MATH, "abs", (primitive,), primitive, "numeric_abs", static=True, **rules)
    for name in ("ceil", "floor"):
        add(MATH, name, ("double",), "double", "floating_" + name, static=True,
            floatingSpecialCases="nan_infinity_signed_zero_preserved")
    for name in ("addExact", "subtractExact", "multiplyExact"):
        for primitive in ("int", "long"):
            add(MATH, name, (primitive, primitive), primitive, name.removesuffix("Exact").lower() + "_checked",
                static=True, exceptions={"java.lang.ArithmeticException": ["integer_overflow"]})
    # multiplyExact(long,int) is more specific than multiplyExact(long,long).
    add(MATH, "multiplyExact", ("long", "int"), "long", "multiply_checked", static=True,
        exceptions={"java.lang.ArithmeticException": ["integer_overflow"]})
    for primitive, returns in (("float", "int"), ("double", "long")):
        add(MATH, "round", (primitive,), returns, "floating_round", static=True, tie="toward_positive_infinity",
            floatingSpecialCases="nan_zero_infinity_and_out_of_range_saturate")

    units = {"Nanos": "nanosecond", "Millis": "millisecond", "Seconds": "second", "Minutes": "minute", "Hours": "hour", "Days": "day_86400_seconds"}
    for suffix, unit in units.items():
        rules = {"unit": unit}
        if suffix in {"Minutes", "Hours", "Days"}: rules["exceptions"] = {"java.lang.ArithmeticException": ["duration_overflow"]}
        add(DURATION, "of" + suffix, ("long",), DURATION, "duration_from_unit", static=True, **rules)
        rules = {"unit": unit, "precision": "nanosecond" if suffix == "Nanos" else "truncate_toward_zero" if suffix == "Millis" else "whole_seconds_division_toward_zero"}
        if suffix == "Seconds": rules["precision"] = "whole_seconds_component"
        if suffix in {"Nanos", "Millis"}: rules["exceptions"] = {"java.lang.ArithmeticException": ["long_overflow"]}
        add(DURATION, "to" + suffix, (), "long", "duration_to_unit", **rules)
    add(DURATION, "ofSeconds", ("long", "long"), DURATION, "duration_seconds_with_nano_adjustment", static=True,
        exceptions={"java.lang.ArithmeticException": ["duration_overflow"]})
    add(DURATION, "between", (TEMPORAL, TEMPORAL), DURATION, "duration_between_temporals", static=True,
        argumentRoles=["start_inclusive", "end_exclusive"], direction="end_minus_start",
        negativeResult="permitted", mixedTypes="calculation_uses_first_temporal_type",
        requiredUnit="SECONDS", fullPrecisionRequires="NANOS_unit_or_NANO_OF_SECOND_field",
        exceptions={"java.time.DateTimeException": ["seconds_between_temporals_unavailable"],
                    "java.lang.ArithmeticException": ["duration_capacity_exceeded"]})
    for name in ("plus", "minus"):
        add(DURATION, name, (DURATION,), DURATION, "duration_" + name, exceptions={"java.lang.ArithmeticException": ["duration_overflow"]})
    add(DURATION, "minusNanos", ("long",), DURATION, "duration_subtract_unit",
        unit="nanosecond", negativeAmount="add", receiverMutation="none",
        exceptions={"java.lang.ArithmeticException": ["duration_overflow"]})
    add(DURATION, "multipliedBy", ("long",), DURATION, "duration_multiply", exceptions={"java.lang.ArithmeticException": ["duration_overflow"]})
    add(DURATION, "dividedBy", ("long",), DURATION, "duration_divide", rounding="toward_zero_nanoseconds",
        exceptions={"java.lang.ArithmeticException": ["zero_divisor", "duration_overflow"]})
    add(DURATION, "dividedBy", (DURATION,), "long", "duration_whole_quotient", rounding="toward_zero",
        exceptions={"java.lang.ArithmeticException": ["zero_divisor", "long_overflow"]})
    add(DURATION, "compareTo", (DURATION,), "int", "duration_compare", outcomes={"less": "negative", "equal": 0, "greater": "positive"})
    for name in ("isZero", "isNegative"):
        add(DURATION, name, (), "boolean", "duration_" + name)
    add(INSTANT, "isBefore", (INSTANT,), "boolean", "instant_before", comparison="strict_timeline_order")
    for name, unit in (("plusMillis", "millisecond"), ("plusSeconds", "second")):
        add(INSTANT, name, ("long",), INSTANT, "instant_add_duration", unit=unit, negativeAmount="subtract",
            exceptions={"java.time.DateTimeException": ["instant_range_exceeded"], "java.lang.ArithmeticException": ["numeric_overflow"]})
    add(TIME_UNIT, "toNanos", ("long",), "long", "time_unit_to_nanoseconds",
        inputUnit="receiver_enum_unit", resultUnit="nanosecond", scaling="integer_multiplication",
        precisionLoss="none_before_saturation", negativeInput="signed_scaling",
        overflow={"negative": "java.lang.Long.MIN_VALUE", "positive": "java.lang.Long.MAX_VALUE"})
    add(SYSTEM, "nanoTime", (), "long", "elapsed_time_clock_read", static=True,
        unit="nanosecond", origin="arbitrary_per_jvm_not_epoch", negativeValues="permitted",
        interpretation="difference_of_readings_from_same_jvm", resolution="not_guaranteed_nanosecond",
        elapsedDifferenceLimit="less_than_2_to_63_nanoseconds", strictlyIncreasing="not_guaranteed")
    add(FUTURE, "whenComplete", (BICONSUMER,), FUTURE, "stage_observe_completion",
        callbackTrigger="receiver_normal_or_exceptional_completion", callbackArguments=["result_or_null", "exception_or_null"],
        dependentCompletion="after_callback_returns", normalResult="receiver_result",
        callbackFailure="dependent_exception_unless_receiver_exception_takes_precedence",
        stageIdentity="new_dependent_stage", callbackThread="completing_thread_or_other_completion_caller",
        genericSignature="CompletableFuture<T>#whenComplete(BiConsumer<? super T,? super Throwable>):CompletableFuture<T>")
    add(FUTURE, "thenApply", (FUNCTION,), FUTURE, "stage_transform_normal_completion",
        callbackTrigger="receiver_normal_completion", callbackArguments=["receiver_result"],
        dependentResult="function_result", receiverFailure="dependent_exceptional_completion",
        callbackFailure="dependent_exceptional_completion", stageIdentity="new_dependent_stage",
        callbackThread="completing_thread_or_other_completion_caller",
        genericSignature="CompletableFuture<T>#thenApply(Function<? super T,? extends U>):CompletableFuture<U>")
    add(FUTURE, "cancel", ("boolean",), "boolean", "stage_cancel",
        precondition="receiver_not_already_completed", receiverOutcome="CancellationException",
        dependentOutcome="not_yet_completed_dependents_CompletionException_caused_by_CancellationException",
        mayInterruptIfRunning="no_effect_in_standard_implementation", result="whether_receiver_is_now_cancelled",
        upstreamCancellation="not_established_by_this_call", underlyingComputationStopped="not_established")
    for suffix, formal in KEY_FUNCTIONS.items():
        rules = {"keyReturnType":suffix.lower() if suffix else "documented_comparable_self",
            "keyDirection":"forward", "actualTargetJdk":"UNKNOWN", "callbackExecution":"UNKNOWN"}
        if not suffix: rules["documentedComparableTypes"] = COMPARABLE_TYPES
        add(COMPARATOR, "comparing"+suffix, (formal,), COMPARATOR, "comparator_key", static=True, **rules)
        add(COMPARATOR, "thenComparing"+suffix, (formal,), COMPARATOR, "comparator_tiebreaker",
            tiePredicate="all_previous_key_comparisons_return_zero", **rules)
    add(COMPARATOR, "reversed", (), COMPARATOR, "comparator_reverse", reversal="receiver_order_only", priorityOrder="unchanged", actualTargetJdk="UNKNOWN")
    for name, code in (("badRequest",400),("notFound",404)):
        add(RESPONSE,name,(),BODY if code==400 else HEADERS,"response_status_factory",static=True,
            publicStatusCode=code,publicStatusName="BAD_REQUEST" if code==400 else "NOT_FOUND")
    for formal in ("int",STATUS):
        add(RESPONSE,"status",(formal,),BODY,"response_status_argument",static=True,statusArgument=0,valueSubstitution=False)
    for receiver in (HEADERS,BODY):
        add(receiver,"build",(),RESPONSE,"response_build",body="none_on_success",status="receiver_builder_status")
        result[(receiver,"build",False)][-1]["declaringType"] = HEADERS
    return result


CONTRACTS = _registry()


def _convertible(actual, formal):
    # Only this documented platform hierarchy edge is needed here. No source
    # subclass, erasure or name-based interface assignability is inferred.
    return actual == formal or formal in WIDEN.get(actual, ()) or (actual, formal) == (INSTANT, TEMPORAL)


def _overload(owner, name, static, arguments):
    if any(arg is None for arg in arguments):
        return None
    applicable = [entry for entry in CONTRACTS.get((owner, name, static), [])
                  if len(entry["parameters"]) == len(arguments)
                  and all(_convertible(arg["name"], formal) for arg, formal in zip(arguments, entry["parameters"]))]
    best = [entry for entry in applicable if all(
        other is entry or all(_convertible(a, b) for a, b in zip(entry["parameters"], other["parameters"]))
        for other in applicable)]
    return best[0] if len(best) == 1 else None


def _catalog_entry(owner_name, name, static, entry):
    owner_name = entry.get("declaringType", owner_name)
    signature = owner_name + "#" + name + "(" + ",".join(entry["parameters"]) + "):" + entry["returnType"]
    exceptions = {key: list(value) for key, value in entry["rules"].get("exceptions", {}).items()}
    if owner_name == BD and name in {"add", "subtract", "multiply", "divide"}:
        exceptions.setdefault("java.lang.ArithmeticException", []).append("possible_scale_overflow_or_underflow")
    if not static: exceptions["java.lang.NullPointerException"] = ["null_receiver"]
    if any(t not in NUMERIC and t != "boolean" for t in entry["parameters"]):
        exceptions.setdefault("java.lang.NullPointerException", []).append("null_reference_argument")
    spring = owner_name.startswith("org.springframework.http.")
    contract_id = ("spring6212:" if spring else "jdk21:") + hashlib.sha256(signature.encode()).hexdigest()[:24]
    value = {"id": contract_id, "schemaVersion": 1, "catalogVersion": "spring-6.2.12-static-contracts-1" if spring else VERSION,
        "resolution": "documented_standard_api_overload", "operation": entry["operation"],
        "declaringType": owner_name, "method": name, "signature": signature,
        "invocationKind": "static" if static else "instance", "parameterTypes": entry["parameters"],
        "result": {"type": entry["returnType"], "value": "UNKNOWN"},
        "rules": {key: value for key, value in entry["rules"].items() if key != "exceptions"},
        "exceptionConditions": exceptions, "exceptionConditionsComplete": False,
        "specification": (SPRING_DOC + owner_name.removeprefix("org.springframework.http.") if spring else DOC_ROOT + owner_name.replace(".", "/")) + ".html#" + name + "(" + ",".join(entry["parameters"]) + ")",
        "scope": "declared_api_contract",
        "runtimeDispatch": "UNKNOWN", "runtimeValue": "UNKNOWN", "executionSuccess": "UNKNOWN"}
    if spring: value["libraryProvenance"] = {"library":"Spring Framework","referenceVersion":"6.2.12",
        "actualTargetVersion":"UNKNOWN","basis":"bounded_documented_library_assumption"}
    return value


def validate_catalog_entry(value, owner, method, static, arguments):
    """Validate the actual operand types against the unchanged JDK catalog."""
    if method=='<init>':
        parameters=_constructor_parameters(owner,arguments) if not static else None
        return parameters is not None and value=={"signature": owner+"#<init>("+",".join(parameters)+")",
            "scope":"declared_constructor_return_type","executionSuccess":"UNKNOWN"}
    selected = _overload(owner, method, static, [{"name": name} for name in arguments])
    if selected is None: return False
    expected = _catalog_entry(owner, method, static, selected)
    return policy_java_platform.canonical(value) == policy_java_platform.canonical(expected)


def _constructor_parameters(owner, arguments):
    if owner!=BD or any(name is None for name in arguments):return None
    base=[("int",),("long",),("double",),("java.lang.String",),("java.math.BigInteger",),("java.math.BigInteger","int")]
    signatures=base+[params+(MC,) for params in base]
    applicable=[params for params in signatures if len(params)==len(arguments)
        and all(_convertible(actual,formal) for actual,formal in zip(arguments,params))]
    best=[params for params in applicable if all(all(_convertible(a,b) for a,b in zip(params,other)) for other in applicable)]
    return best[0] if len(best)==1 else None


def _type(name, evidence, basis, *parents):
    return policy_java_platform.inherit({"name": name, "resolution": "resolved_static_type", "basis": basis,
            "sourceEvidenceIds": sorted(set(evidence))}, *parents)


def _receiver_bridge(receiver_type, catalog_entry):
    return {"schemaVersion":1,"capability":"spring-response-receiver-bridge-1","actualReceiverType":BODY,
        "declaringType":HEADERS,"method":"build","argumentCount":0,"invocationKind":"instance",
        "relation":"documented_direct_superinterface_member","catalogContractId":catalog_entry["id"],
        "sourceEvidenceIds":receiver_type["sourceEvidenceIds"],"referenceVersion":"6.2.12","actualTargetVersion":"UNKNOWN",
        "specification":SPRING_DOC+"ResponseEntity.BodyBuilder.html","runtimeDispatch":"UNKNOWN","executionSuccess":"UNKNOWN"}


def validate_receiver_bridge(bridge, *, receiver_type, catalog_entry, method, static, arguments):
    """Validate only this finite edge; callers must also close receiver proof."""
    return (isinstance(receiver_type,dict) and receiver_type.get("name")==BODY and method=="build"
        and static is False and arguments==[] and validate_catalog_entry(catalog_entry,BODY,"build",False,[])
        and policy_java_platform.canonical(bridge)==policy_java_platform.canonical(_receiver_bridge(receiver_type,catalog_entry)))


def _status_argument_admitted(argument, fragment_id):
    if argument.get("op") in {"masked_value","redacted","opaque_literal","unresolved"}:return False
    if argument.get("op")!="literal":return True  # existing expression proof validation still applies
    # _numeric already performed privacy/lexical checks. Revalidate its actual
    # emitted AST and type, without reading a source token or copying a value.
    value=argument.get("value")
    return (argument.get("type")=="integer" and argument.get("javaSuffix") is None
        and "literalReview" not in argument and isinstance(value,str) and value.isascii() and value.isdigit()
        and (value=="0" or not value.startswith("0")) and len(value)<=10 and int(value)<=2147483647
        and argument.get("staticType")==_type("int",[fragment_id],"java_literal_type"))


def _response_contract(node, path, receiver, paths, evidence):
    name=node.get("callee",{}).get("name","").rsplit(".",1)[-1]
    previous=(receiver or {}).get("staticContract",{}).get("responseStatusContract")
    result={"schemaVersion":1,"capability":"spring-response-status-1","resolution":"documented_static_status_relation",
        "factoryCallPointer":None,"builderReceiverPointer":paths.get(id(receiver)),"statusOrigin":"unproven_builder",
        "statusCode":None,"statusName":"UNKNOWN","statusArgumentPointer":None,"statusArgumentValue":"UNKNOWN",
        "statusArgumentReview":"not_applicable","constructionStage":"built_response" if name=="build" else "builder",
        "bodyContract":"no_body_on_success" if name=="build" else "not_built","sourceEvidenceIds":sorted(set(evidence)),
        "actualTargetVersion":"UNKNOWN","runtimeDispatch":"UNKNOWN","executionSuccess":"UNKNOWN","responseDelivery":"UNKNOWN"}
    if name in {"badRequest","notFound"}:
        result.update(factoryCallPointer=path,statusOrigin="public_api_constant",statusCode=400 if name=="badRequest" else 404,
            statusName="BAD_REQUEST" if name=="badRequest" else "NOT_FOUND")
    elif name=="status":
        arg=node["arguments"][0]
        result.update(factoryCallPointer=path,statusOrigin="source_argument",statusArgumentPointer=path+"/arguments/0",
            statusArgumentReview="admitted" if isinstance(arg.get("literalReview"),dict) else "not_applicable" if arg.get("op")=="literal" else "not_a_literal")
    elif previous:
        for key in ("factoryCallPointer","statusOrigin","statusCode","statusName","statusArgumentPointer","statusArgumentReview"):
            result[key]=previous[key]
    return result


def _syntax_nodes(expression):
    pending=[(expression,"/expression")]; examined=0
    while pending:
        value,path=pending.pop(); examined+=1
        if examined>20_000:raise ValueError("c29_traversal_budget_exceeded")
        if isinstance(value,dict):
            if "op" in value:yield value,path
            pending.extend((v,path+"/"+k) for k,v in value.items()
                if k not in {"staticType","staticContract","staticContractStatus","sourceRange","parameterRanges"} and isinstance(v,(dict,list)))
        elif isinstance(value,list):pending.extend((v,path+"/"+str(i)) for i,v in enumerate(value))


def _range_contains(outer, inner):
    return (isinstance(outer,dict) and isinstance(inner,dict) and set(inner)=={"charStart","charEnd"}
        and all(type(x) is int for x in (outer.get("charStart"),outer.get("charEnd"),inner.get("charStart"),inner.get("charEnd")))
        and 0<=outer["charStart"]<=inner["charStart"]<inner["charEnd"]<=outer["charEnd"])


def _explicit_type_roles(method):
    if method=="comparing":return ("T","U")
    if method in {"comparingInt","comparingLong","comparingDouble"}:return ("T",)
    if method=="thenComparing":return ("U",)
    return ()


def _explicit_type_spellings(callee):
    # The existing AST stores lexical tokens, including dots and commas. Keep
    # that wire shape; recognize only a finite list of plain qualified names.
    tokens=callee.get("typeArguments",[])
    if not isinstance(tokens,list) or not tokens or len(tokens)>512:return None
    result=[];parts=[];expect_name=True
    for token in tokens:
        if not isinstance(token,str):return None
        if expect_name:
            if not policy_java_platform.declaration_identifier(token):return None
            parts.append(token);expect_name=False
        elif token==".":expect_name=True
        elif token==",":
            result.append(".".join(parts));parts=[];expect_name=True
        else:return None
    if expect_name:return None
    return result+[".".join(parts)]


def _explicit_input_type(callee, method):
    roles=_explicit_type_roles(method);arguments=_explicit_type_spellings(callee)
    return arguments[0] if arguments and roles and roles[0]=="T" and len(arguments)==len(roles) else None


def _explicit_arguments_valid(callee, method, input_type, key_type, matches):
    if "typeArguments" not in callee:return True
    arguments=_explicit_type_spellings(callee);roles=_explicit_type_roles(method)
    # Explicit arguments on the nongeneric methods are outside this subset;
    # this is not a claim that Java forbids such invocation syntax.
    return (isinstance(arguments,list) and bool(roles) and len(arguments)==len(roles)
        and all(matches(raw,input_type if role=="T" else key_type)
            for raw,role in zip(arguments,roles)))


def _ordering(node, path, receiver, receiver_path, binding, evidence):
    """Compose only the immediately proved receiver; never follow variables."""
    prior=(receiver or {}).get("staticContract",{}).get("orderingContract")
    name=node["callee"]["name"].rsplit(".",1)[-1]
    if name=="reversed":
        if not prior:return None
        result=json.loads(json.dumps(prior))
        for key in result["keys"]:
            key["direction"]="reverse" if key["direction"]=="forward" else "forward"
            key["reversalCallPointers"].append(path)
    else:
        if not binding or name.startswith("then") and not prior:return None
        result=json.loads(json.dumps(prior)) if prior else {
            "schemaVersion":1,"capability":"java-comparator-ordering-1","resolution":"documented_static_composition",
            "inputType":binding["inputType"],"keys":[],"tiePredicate":"all_previous_key_comparisons_return_zero",
            "actualTargetJdk":"UNKNOWN","runtimeDispatch":"UNKNOWN","runtimeValue":"UNKNOWN","executionSuccess":"UNKNOWN"}
        if result["inputType"]!=binding["inputType"]:return None
        natural=next((c["id"] for c in COMPARABLE_TYPES if c["qualifiedName"]==binding["returnType"]),None)
        result["keys"].append({"priority":len(result["keys"]),"keyExtractorPointer":binding["callbackPointer"],
            "keyType":binding["returnType"],"keyOrderKind":"documented_natural_comparable" if natural else "primitive_"+binding["returnType"],
            "naturalTypeContractId":natural,"direction":"forward","introducedByCallPointer":path,
            "callbackBindingPointer":path+"/staticContract/callbackBinding","reversalCallPointers":[]})
    result["receiverPointer"]=receiver_path if prior else None
    result["sourceEvidenceIds"]=sorted(set(evidence))
    return result


def validate_composition(value, output, *, lookup=None, allow_pending=False):
    """Validate optional C29 meaning against delivered syntax and providers.

    No source text, runtime, or arbitrary nominal inheritance is consulted.
    Called for every derived field, including those with no platform checks.
    """
    try:
        targets=set();work=[value];count=0
        while work:
            current=work.pop();count+=1
            if count>20_000:return "c29_traversal_budget_exceeded"
            if isinstance(current,(dict,list)):
                targets.add(id(current))
                work.extend(current.values() if isinstance(current,dict) else current)
        nodes=list(_syntax_nodes(output.get("expression",{})));paths={id(n):p for n,p in nodes}
        bound_callbacks={id(n["arguments"][0]) for n,p in nodes if n.get("arguments") and
            n.get("staticContract",{}).get("callbackBinding",{}).get("capability")=="java-source-key-callback-1"}
        for n,p in nodes:
            typed=n.get("staticType",{})
            if (typed.get("basis")=="source_callback_functional_target" and id(typed) in targets
                    and id(n) not in bound_callbacks):return "source_callback_binding_missing"
        catalogs=output.get("standardApiContracts",[])
        catalog={c.get("id"):c for c in catalogs}
        if len(catalog)!=len(catalogs):return "c29_catalog_ambiguous"
        callback_count=sum(n.get("staticContract",{}).get("callbackBinding",{}).get("capability")=="java-source-key-callback-1" for n,p in nodes)
        added_bytes=sum(len(policy_java_platform.canonical(n["staticContract"][k])) for n,p in nodes
            for k in ("orderingContract","responseStatusContract","receiverBridge","callbackBinding")
            if k in n.get("staticContract",{}) and (k!="callbackBinding" or n["staticContract"][k].get("capability")=="java-source-key-callback-1"))
        for node,path in nodes:
            contract=node.get("staticContract",{})
            diagnostic=node.get("staticContractStatus",{}).get("statusArgument")
            if diagnostic is not None and id(diagnostic) in targets:
                expected={"schemaVersion":1,"capability":"spring-response-status-1","argumentIndex":0,
                    "argumentPointer":path+"/arguments/0","value":"UNKNOWN"}
                if (policy_java_platform.canonical(diagnostic)!=policy_java_platform.canonical(expected)
                        or len(node.get("arguments",[]))!=1 or node.get("callee",{}).get("name","").rsplit(".",1)[-1]!="status"
                        or node.get("callee",{}).get("ownerStaticType",{}).get("name")!=RESPONSE):return "c29_status_diagnostic_invalid"
            entry=catalog.get(contract.get("contractId"),{})
            callback=contract.get("callbackBinding",{})
            candidate_fields=[node.get("staticType"),contract,callback,node.get("arguments",[{}])[0].get("staticType") if node.get("arguments") else None]
            if not any(id(x) in targets for x in candidate_fields if isinstance(x,dict)):continue
            special=entry.get("declaringType") in {COMPARATOR,RESPONSE,BODY,HEADERS}
            if not special:
                if any(k in contract for k in ("orderingContract","responseStatusContract","receiverBridge")) or callback.get("capability")=="java-source-key-callback-1":return "c29_catalog_unavailable"
                continue
            if added_bytes>32*1024:return "c29_metadata_budget_exceeded"
            if node.get("op")!="call":return "c29_shape_invalid"
            callee=node.get("callee",{});name=callee.get("name","").rsplit(".",1)[-1]
            receiver=callee.get("receiver") if callee.get("op")=="member" else None
            owner=callee.get("ownerStaticType") or callee.get("receiverStaticType") or (receiver or {}).get("staticType",{})
            static="ownerStaticType" in callee
            args=[a.get("staticType",{}) for a in node.get("arguments",[])]
            if (not owner or not validate_catalog_entry(entry,owner.get("name"),name,static,[a.get("name") for a in args])
                    or contract.get("catalogLocation")!="fragment.standardApiContracts"):return "c29_catalog_operand_invalid"
            evidence=sorted(set(owner.get("sourceEvidenceIds",[])+[output["id"]]+[i for a in args for i in a.get("sourceEvidenceIds",[])]))
            operands=[{"role":"argument","argumentIndex":i,"actualType":a.get("name"),"formalType":formal,
                "sourceEvidenceIds":a.get("sourceEvidenceIds")} for i,(a,formal) in enumerate(zip(args,entry["parameterTypes"]))]
            if not static:operands.insert(0,{"role":"receiver","actualType":owner["name"],"sourceEvidenceIds":owner.get("sourceEvidenceIds")})
            if policy_java_platform.canonical(contract.get("operands"))!=policy_java_platform.canonical(operands) or contract.get("sourceEvidenceIds")!=evidence:return "c29_operand_evidence_invalid"
            fields={"contractId","operands","sourceEvidenceIds","catalogLocation"}
            if "platformInheritance" in contract:fields.add("platformInheritance")
            if owner["name"]==COMPARATOR:
                fields.add("orderingContract")
                if name!="reversed":
                    fields.add("callbackBinding")
                    failure=_validate_callback(callback,node,path,output,lookup)
                    if failure:return "dependency_pending_snapshot_finalization" if allow_pending and failure=="source_callback_provider_unavailable" else failure
                elif callback:return "source_callback_shape_invalid"
                if name=="reversed" and "typeArguments" in callee:return "comparator_explicit_type_arguments_unsupported"
                expected=_ordering(node,path,receiver,paths.get(id(receiver)),callback,evidence)
                if (expected is None or policy_java_platform.canonical(contract.get("orderingContract"))!=policy_java_platform.canonical(expected) or callback_count>16
                        or len(expected["keys"])>16 or any(len(k["reversalCallPointers"])>16 for k in expected["keys"])):return "c29_ordering_invalid_or_budget_exceeded"
                if (node.get("staticType",{}).get("typeArguments")!=[expected["inputType"]]
                        or node.get("staticType",{}).get("typeArgumentsStatus")!="resolved"):return "c29_ordering_type_invalid"
            else:
                fields.add("responseStatusContract")
                if name=="status" and any(not _status_argument_admitted(a,output["id"]) for a in node.get("arguments",[])):return "c29_status_argument_unreviewed"
                if policy_java_platform.canonical(contract.get("responseStatusContract"))!=policy_java_platform.canonical(_response_contract(node,path,receiver,paths,evidence)):return "c29_response_status_invalid"
                if owner["name"]==BODY and name=="build":
                    fields.add("receiverBridge")
                    if not validate_receiver_bridge(contract.get("receiverBridge"),receiver_type=owner,catalog_entry=entry,method=name,static=static,arguments=[]):return "c29_receiver_bridge_invalid"
            if set(contract)!=fields:return "c29_contract_shape_invalid"
            if len(policy_java_platform.canonical(contract))>32*1024:return "c29_metadata_budget_exceeded"
        return None
    except (KeyError,TypeError,ValueError,AttributeError,IndexError):
        return "c29_composition_malformed"


def validate_callback_type_namespace(owner, lookup, known_types=()):
    """Validate optional source-bound names; absence never follows failed lookup."""
    value=owner.get("callbackTypeNamespace",{})
    fields={"schemaVersion","scope","sourceDigest","declarations","detectedDeclarations","omittedDeclarations","status","reason"}
    entry_fields={"recordId","name","qualifiedName","path","sourceDigest","sourceRange","relation"}
    if (set(value)!=fields or type(value.get("schemaVersion")) is not int or value["schemaVersion"]!=1
            or value.get("scope")!="bounded_selected_lexical_and_package_type_names" or value.get("sourceDigest")!=owner.get("sourceDigest")
            or value.get("status") not in {"complete","UNKNOWN"}
            or value.get("reason") not in {None,"source_type_namespace_unverified","type_namespace_budget_exceeded","duplicate_type_namespace_identity"}
            or any(type(value.get(k)) is not int or value[k]<0 for k in ("detectedDeclarations","omittedDeclarations"))
            or not isinstance(value.get("declarations"),list) or len(value["declarations"])>64
            or value["detectedDeclarations"]!=len(value["declarations"])+value["omittedDeclarations"]
            or value["status"]=="complete" and (value["omittedDeclarations"] or value["reason"] is not None)
            or value["status"]=="UNKNOWN" and value["reason"] is None):return False
    if value["status"]=="complete" and (owner.get("directMemberInventory",{}).get("fields")!="complete"
            or owner.get("directMemberInventory",{}).get("memberTypes")!="complete" or owner.get("directMemberInventory",{}).get("reasons")):return False
    ids=set();names=set()
    for item in value["declarations"]:
        if (not isinstance(item,dict) or set(item)!=entry_fields or not isinstance(item.get("recordId"),str)
                or item["recordId"] in ids or not isinstance(item.get("name"),str)
                or not policy_java_platform.declaration_identifier(item["name"])
                or item.get("relation") not in {"direct_member","local_or_nonmember","same_package_top_level"}
                or (item["relation"],item["name"]) in names):return False
        ids.add(item["recordId"]);names.add((item["relation"],item["name"]))
        declared=lookup(item["recordId"],item.get("path")) if lookup else None
        if (not isinstance(declared,dict) or declared.get("kind")!="symbol" or declared.get("type") not in {"Class","Interface","Record","Enum"}
                or declared.get("id")!=item["recordId"] or declared.get("structuralOnly")
                or declared.get("dependencyClosure",{}).get("status") in {"invalidated","pending_snapshot_finalization"}
                or any(item.get(key)!=declared.get(key) for key in ("name","qualifiedName","path","sourceDigest","sourceRange"))
                or not _range_contains(declared.get("sourceRange"),declared.get("bodyRange"))):return False
        eligibility=declared.get("typeDeclarationEligibility",{})
        if (set(eligibility)!={"schemaVersion","status","modifiers","enclosingTypeId","scope"}
                or type(eligibility.get("schemaVersion")) is not int or eligibility["schemaVersion"]!=1
                or eligibility.get("status")!="source_header_only"
                or eligibility.get("scope")!="named_type_access_not_compiler_validity"):return False
        enclosing=eligibility["enclosingTypeId"]
        if item["relation"]=="same_package_top_level":
            if enclosing is not None or declared.get("sourcePackage")!=owner.get("sourcePackage"):return False
            if declared.get("qualifiedName")!=(owner.get("sourcePackage","")+"."+item["name"]).strip("."):return False
        elif (enclosing!=owner.get("id") or item["path"]!=owner.get("path") or item["sourceDigest"]!=owner.get("sourceDigest")
                or item["qualifiedName"]!=owner.get("qualifiedName","")+"."+item["name"]
                or not _range_contains(owner.get("bodyRange"),item["sourceRange"])):return False
    if not isinstance(known_types,(list,tuple)) or len(known_types)>64:return False
    if value["status"]!="complete":return True  # Raw UNKNOWN is not an absence proof.
    mandatory=[];scope=owner;seen=set()
    while scope:
        if scope.get("id") in seen or len(seen)>=16:return False
        seen.add(scope.get("id"));mandatory.append(scope)
        eligibility=scope.get("typeDeclarationEligibility",{})
        if (set(eligibility)!={"schemaVersion","status","modifiers","enclosingTypeId","scope"}
                or type(eligibility.get("schemaVersion")) is not int or eligibility["schemaVersion"]!=1
                or eligibility.get("status")!="source_header_only"):return False
        parent=eligibility["enclosingTypeId"]
        if parent:
            enclosing=lookup(parent,scope.get("path")) if lookup else None
            if (not enclosing or enclosing.get("id")!=parent or enclosing.get("path")!=scope.get("path")
                    or enclosing.get("sourceDigest")!=scope.get("sourceDigest")
                    or not _range_contains(enclosing.get("bodyRange"),scope.get("sourceRange"))):return False
            scope=enclosing
        else:scope=None
    known={}
    for record in [*mandatory,*known_types]:
        if (not isinstance(record,dict) or record.get("kind")!="symbol" or record.get("type") not in {"Class","Interface","Record","Enum"}
                or not isinstance(record.get("id"),str) or not isinstance(record.get("path"),str)):return False
        actual=lookup(record["id"],record["path"]) if lookup else None
        if not actual or policy_java_platform.canonical(actual)!=policy_java_platform.canonical(record):return False
        if record["id"] in known and policy_java_platform.canonical(known[record["id"]])!=policy_java_platform.canonical(record):return False
        known[record["id"]]=record
    # Counts and a digest cannot certify absence. Independently known source
    # providers must also appear, even when another proof role uses their ID.
    if value["status"]=="complete":
        entries={item["recordId"]:item for item in value["declarations"]};relevant=0
        for record in known.values():
            eligibility=record.get("typeDeclarationEligibility",{})
            if "enclosingTypeId" not in eligibility:return False
            parent=eligibility["enclosingTypeId"]
            package_member=parent is None and record.get("sourcePackage")==owner.get("sourcePackage")
            lexical_child=parent==owner.get("id")
            if not package_member and not lexical_child:continue
            relevant+=1
            if relevant>64:return False
            item=entries.get(record["id"])
            if item is None:return False
            if package_member and item["relation"]!="same_package_top_level":return False
            if lexical_child and item["relation"] not in {"direct_member","local_or_nonmember"}:return False
    return True


def _explicit_type_context(caller, callable_owner, lookup, known_types):
    scopes=[];ids=set();scope=caller;seen=set()
    while scope:
        if (scope.get("id") in seen or len(seen)>=16 or scope.get("extendsTypes") or scope.get("implementsTypes")
                or not validate_callback_type_namespace(scope,lookup,known_types) or scope["callbackTypeNamespace"]["status"]!="complete"):
            return None
        seen.add(scope["id"]);scopes.append(scope)
        ids.update(item["recordId"] for item in scope["callbackTypeNamespace"]["declarations"])
        parent=scope.get("typeDeclarationEligibility",{}).get("enclosingTypeId")
        if parent:
            enclosing=lookup(parent,scope.get("path")) if lookup else None
            if (not enclosing or enclosing.get("id")!=parent or enclosing.get("path")!=scope.get("path")
                    or enclosing.get("sourceDigest")!=scope.get("sourceDigest")
                    or not _range_contains(enclosing.get("bodyRange"),scope.get("sourceRange"))):return None
            scope=enclosing
        else:scope=None
    variables={p.get("name") for scope in scopes+[callable_owner] for p in scope.get("typeParameters",[])}
    def matches(raw, expected):
        head,_,tail=raw.partition(".");suffix="."+tail if tail else ""
        if head in variables or not policy_java_platform.source_type_matches(raw,expected,caller):return False
        for scope in scopes:
            declarations=scope["callbackTypeNamespace"]["declarations"]
            if any(item["name"]==head and item["relation"]=="local_or_nonmember" for item in declarations):return False
            members=[item for item in declarations if item["name"]==head and item["relation"]=="direct_member"]
            if members:return len(members)==1 and members[0]["qualifiedName"]+suffix==expected
            if scope.get("name")==head:return scope["qualifiedName"]+suffix==expected
        imports=caller.get("typeImports",[])
        explicit={item.get("qualifiedName") for item in imports if item.get("kind")=="type"
            and item.get("qualifiedName","").rsplit(".",1)[-1]==head}
        if any(item.get("kind")=="static" and (item.get("qualifiedName","").endswith(".*")
                or item.get("qualifiedName","").rsplit(".",1)[-1]==head) for item in imports):return False
        if explicit:return len(explicit)==1 and next(iter(explicit))+suffix==expected
        package=[item for item in caller["callbackTypeNamespace"]["declarations"]
            if item["relation"]=="same_package_top_level" and item["name"]==head]
        return not package or len(package)==1 and package[0]["qualifiedName"]+suffix==expected
    return ids,matches


def _validate_callback(binding,node,path,output,lookup):
    cb=node["arguments"][0]; evidence=binding.get("declarationEvidence",{})
    provider=lookup(evidence.get("recordId"),evidence.get("path")) if lookup else None
    caller=lookup(output.get("javaSourceOwner",{}).get("typeSymbolId"),output.get("path")) if lookup else None
    if provider is None or caller is None:return "source_callback_provider_unavailable"
    if provider.get("kind")!="symbol" or provider.get("sourceDigest")!=evidence.get("sourceDigest") or provider.get("path")!=evidence.get("path"):return "source_callback_provider_invalid"
    method_decl=provider.get("callbackDeclaration",{})
    owner=provider if evidence.get("evidenceKind")=="existing_record_component_accessor" else lookup(method_decl.get("ownerTypeId"),provider["path"])
    if not owner:return "source_callback_provider_unavailable"
    inventory=owner.get("callbackMemberInventory",{})
    if (set(inventory)!={"schemaVersion","scope","sourceDigest","declarationIds","detectedDeclarations","omittedDeclarations","selectedTypeDeclarationCount","status","reason"}
            or type(inventory.get("schemaVersion")) is not int or inventory.get("schemaVersion")!=1 or inventory.get("scope")!="bounded_direct_indexed_method_headers"
            or any(type(inventory.get(k)) is not int for k in ("detectedDeclarations","omittedDeclarations","selectedTypeDeclarationCount"))
            or inventory.get("status")!="complete" or inventory.get("reason") is not None or inventory.get("omittedDeclarations")!=0
            or inventory.get("selectedTypeDeclarationCount")!=1 or inventory.get("sourceDigest")!=owner.get("sourceDigest")
            or not isinstance(inventory.get("declarationIds"),list) or len(inventory["declarationIds"])>64
            or inventory.get("detectedDeclarations")!=len(inventory["declarationIds"])
            or len(set(inventory["declarationIds"]))!=len(inventory["declarationIds"])
            or owner.get("type") not in {"Class","Record"} or owner.get("typeParameters") or owner.get("extendsTypes") or owner.get("implementsTypes")
            or owner.get("qualifiedName")!=binding.get("inputType")
            or owner.get("directMemberInventory",{}).get("fields")!="complete"
            or owner.get("directMemberInventory",{}).get("memberTypes")!="complete"
            or owner.get("directMemberInventory",{}).get("reasons")
            or not policy_java_platform.declared_type_accessible(owner,caller,lookup)):return "source_callback_provider_invalid"
    form=binding.get("form"); raw=None; name=None; parameter=None; parameter_range=None
    if cb.get("op")=="method_reference" and cb.get("receiver",{}).get("op")=="reference":
        raw=cb["receiver"]["name"];name=cb["name"];expected_form="unbound_instance_method_reference"
    elif cb.get("op")=="lambda":
        params=cb.get("parameters",[]);ranges=cb.get("parameterRanges",[])
        if len(params)!=1 or len(ranges)!=1:return "source_callback_shape_invalid"
        p=params[0]; tokens=p if isinstance(p,list) else [p.get("name")] if isinstance(p,dict) and p.get("op")=="reference" else []
        if not tokens:return "source_callback_shape_invalid"
        parameter=tokens[-1];parameter_range=ranges[0]
        if len(tokens)>1:raw="".join(tokens[:-1]);expected_form="explicitly_typed_expression_lambda"
        else:
            receiver=node.get("callee",{}).get("receiver",{})
            raw=receiver.get("staticContract",{}).get("orderingContract",{}).get("inputType")
            raw=raw or _explicit_input_type(node.get("callee",{}),node.get("callee",{}).get("name","").rsplit(".",1)[-1]);expected_form="receiver_typed_expression_lambda"
        body=cb.get("body",{});callee=body.get("callee",{})
        if (body.get("op")!="call" or body.get("arguments")!=[] or callee.get("op")!="reference"
                or callee.get("typeArguments") or not callee.get("name","").startswith(parameter+".")):return "source_callback_shape_invalid"
        name=callee["name"][len(parameter)+1:]
    else:return "source_callback_shape_invalid"
    if not raw or "." in name or not policy_java_platform.source_type_matches(raw,binding.get("inputType"),caller):return "source_callback_shape_invalid"
    head=raw.split(".",1)[0]
    callable_owner=lookup(output.get("javaSourceOwner",{}).get("callableSymbolId"),output.get("path"))
    if (not callable_owner or any(p.get("name")==head for p in caller.get("typeParameters",[])+callable_owner.get("typeParameters",[]))):return "source_callback_shape_invalid"
    if expected_form=="unbound_instance_method_reference" and (
            head in caller.get("directMemberInventory",{}).get("fieldNames",[])
            or any(p.get("name")==head for p in callable_owner.get("parameterTypeReferences",[]))
            or any(r.get("name")==raw and r.get("declarations") for r in output.get("references",[]))):return "source_callback_shape_invalid"
    members=[]
    declaration_fields={"schemaVersion","scope","ownerTypeId","headerRange","invocationKind","access","varargs","generic","hasBody","declarationValidity"}
    for identity in inventory["declarationIds"]:
        member=lookup(identity,owner["path"])
        if member is None:return "source_callback_provider_unavailable"
        d=member.get("callbackDeclaration",{})
        if (member.get("id")!=identity or member.get("kind")!="symbol" or member.get("type")!="Method"
                or member.get("owner")!=owner.get("qualifiedName") or member.get("path")!=owner.get("path")
                or member.get("sourceDigest")!=owner.get("sourceDigest") or not _range_contains(owner.get("sourceRange"),member.get("sourceRange"))
                or set(d)!=declaration_fields or type(d.get("schemaVersion")) is not int or d.get("schemaVersion")!=1 or d.get("scope")!="bounded_source_method_header"
                or member.get("structuralOnly") or member.get("dependencyClosure",{}).get("status") in {"invalidated","pending_snapshot_finalization"}
                or d.get("ownerTypeId")!=owner.get("id") or not _range_contains(member.get("sourceRange"),d.get("headerRange"))
                or d.get("headerRange")!={"charStart":member["sourceRange"]["charStart"],
                    "charEnd":member.get("bodyRange",{}).get("charStart",member["sourceRange"]["charEnd"]-1)+1}
                or d.get("hasBody") is not ("bodyRange" in member)
                or d.get("invocationKind") not in {"static","instance"} or d.get("access") not in {"public","protected","private","package","UNKNOWN"}
                or any(type(d.get(k)) is not bool for k in ("varargs","generic","hasBody"))
                or d.get("declarationValidity") not in {"bounded_header_only","UNKNOWN"}):return "source_callback_provider_invalid"
        if member.get("name")==name:members.append(member)
    if evidence.get("evidenceKind")=="selected_method_signature":
        if len(members)!=1 or members[0]!=provider:return "source_callback_provider_invalid"
        d=method_decl;access=d["access"]
        package=owner["sourcePackage"];local=owner["qualifiedName"][len(package)+1:] if package else owner["qualifiedName"]
        nest=(package+"." if package else "")+local.split(".",1)[0]
        same_nest=caller["qualifiedName"]==nest or caller["qualifiedName"].startswith(nest+".")
        if (d["invocationKind"]!="instance" or d["varargs"] or d["generic"] or not d["hasBody"] or d["declarationValidity"]!="bounded_header_only"
                or provider.get("parameterTypes") or provider.get("typeParameters") or access=="UNKNOWN"
                or access=="private" and not same_nest or access in {"package","protected"} and caller["sourcePackage"]!=package):return "source_callback_provider_invalid"
        returned=provider.get("returnTypeReference",{})
        expected_evidence={"recordId":provider["id"],"selector":"/callbackDeclaration","path":provider["path"],
            "sourceDigest":provider["sourceDigest"],"sourceRange":provider["sourceRange"],"returnTypeSelector":"/returnTypeReference","evidenceKind":"selected_method_signature"}
        result=returned.get("resolvedType")
        if (returned.get("resolution") not in {"resolved","primitive"} or returned.get("genericArguments") or returned.get("arrayDimensions")
                or not policy_java_platform.source_type_matches(returned.get("rawType"),result,owner)):return "source_callback_provider_invalid"
        if result and result.startswith("java.lang.") and result[10:] in {"int","long","double"}:result=result[10:]
    elif evidence.get("evidenceKind")=="existing_record_component_accessor":
        if members or owner.get("type")!="Record":return "source_callback_provider_invalid"
        components=owner.get("recordComponents",[]);matches=[(i,c) for i,c in enumerate(components) if c.get("name")==name]
        if len(matches)!=1:return "source_callback_provider_invalid"
        i,component=matches[0]
        if component.get("declarationStatus")!="declared" or component.get("typeResolution") not in {"resolved","primitive"}:return "source_callback_provider_invalid"
        result=component.get("type")
        if (component.get("index")!=i or not _range_contains(owner.get("recordHeaderRange"),component.get("sourceRange"))
                or not policy_java_platform.source_type_matches(component.get("declaredType"),result,owner)):return "source_callback_provider_invalid"
        if result and result.startswith("java.lang.") and result[10:] in {"int","long","double"}:result=result[10:]
        expected_evidence={"recordId":owner["id"],"selector":"/recordComponents/"+str(i),"path":owner["path"],"sourceDigest":owner["sourceDigest"],
            "sourceRange":component["sourceRange"],"returnTypeSelector":"/recordComponents/"+str(i),"evidenceKind":"existing_record_component_accessor"}
    else:return "source_callback_provider_invalid"
    method=node["callee"]["name"].rsplit(".",1)[-1];suffix=method.removeprefix("thenComparing").removeprefix("comparing")
    if suffix not in KEY_FUNCTIONS or (result!=suffix.lower() if suffix else result not in {x["qualifiedName"] for x in COMPARABLE_TYPES}):return "source_callback_return_invalid"
    known_types=[]
    if "typeArguments" in node["callee"]:
        identities=binding.get("sourceEvidenceIds")
        if not isinstance(identities,list) or len(identities)>62 or any(not isinstance(i,str) for i in identities):return "source_callback_provider_invalid"
        known={owner["id"]:owner,caller["id"]:caller}
        for identity in identities:
            record=lookup(identity,None) if lookup else None
            if not record:return "source_callback_provider_unavailable"
            if record.get("kind")=="symbol" and record.get("type") in {"Class","Interface","Record","Enum"}:known[identity]=record
        for start in (owner,caller):
            scope=start;seen=set()
            while scope:
                if scope.get("id") in seen or len(seen)>=16:return "source_callback_provider_invalid"
                seen.add(scope["id"]);known[scope["id"]]=scope
                parent=scope.get("typeDeclarationEligibility",{}).get("enclosingTypeId")
                scope=lookup(parent,scope.get("path")) if parent and lookup else None
                if parent and scope is None:return "source_callback_provider_unavailable"
        if len(known)>64:return "source_callback_provider_invalid"
        known_types=list(known.values())
    context=_explicit_type_context(caller,callable_owner,lookup,known_types) if "typeArguments" in node["callee"] else (set(),lambda raw,expected:False)
    if context is None or not _explicit_arguments_valid(node["callee"],method,owner["qualifiedName"],result,context[1]):return "comparator_explicit_type_arguments_unproven"
    enclosing_ids=[]
    for start in (owner,caller):
        scope=start;seen=set()
        while scope:
            if scope["id"] in seen or len(seen)>=16:return "source_callback_provider_invalid"
            seen.add(scope["id"]);enclosing_ids.append(scope["id"])
            parent_id=scope.get("typeDeclarationEligibility",{}).get("enclosingTypeId")
            if parent_id:
                scope=lookup(parent_id,scope["path"])
                if scope is None:return "source_callback_provider_unavailable"
            else:scope=None
    ids=sorted(set(enclosing_ids+inventory["declarationIds"]+list(context[0])))
    if len(ids)>62:return "source_callback_provider_invalid"
    expected={"schemaVersion":1,"capability":"java-source-key-callback-1","callbackArgument":0,"callbackPointer":path+"/arguments/0",
        "sourceRange":cb.get("sourceRange"),"form":expected_form,"inputType":owner["qualifiedName"],"returnType":result,
        "targetFunctionalInterface":KEY_FUNCTIONS[suffix],"parameterName":parameter,"parameterRange":parameter_range,
        "declarationEvidence":expected_evidence,"sourceEvidenceIds":ids,"bindingScope":"declared_callback_signature_only",
        "runtimeDispatch":"UNKNOWN","bodyExecution":"UNKNOWN","javaTypeCheckSuccess":"UNKNOWN"}
    if (len(ids)>62 or not _range_contains(output.get("sourceRange"),cb.get("sourceRange"))
            or parameter_range and not _range_contains(cb["sourceRange"],parameter_range)
            or policy_java_platform.canonical(binding)!=policy_java_platform.canonical(expected)
            or cb.get("staticType")!=_type(KEY_FUNCTIONS[suffix],ids,"source_callback_functional_target")):return "source_callback_binding_invalid"
    return None


def enrich(expression, *, reference_type, type_name, call_result, fragment_id, record_accessor=None, static_import=None,
           record_call_result=None, platform_projection=None, node_scope=None, callback_signature=None, callback_shadowed=None):
    """Decorate one bounded AST; callbacks supply validated lexical evidence."""
    catalog = {}
    paths = {}; pending = [(expression,"/expression")]
    while pending:
        value, location = pending.pop()
        if isinstance(value,dict):
            if "op" in value: paths[id(value)] = location
            pending.extend((v,location+"/"+k) for k,v in value.items() if isinstance(v,(dict,list)))
        elif isinstance(value,list): pending.extend((v,location+"/"+str(i)) for i,v in enumerate(value))
    def callback_proof(callback, callee, name, receiver_order):
        if not callback_signature or not isinstance(callback,dict) or not callback.get("sourceRange"): return None
        expected = receiver_order.get("inputType") if receiver_order else None
        raw = None; method = None; parameter = None; parameter_range = None
        if callback.get("op") == "method_reference" and callback.get("receiver",{}).get("op") == "reference":
            raw = callback["receiver"]["name"]; method = callback["name"]; form = "unbound_instance_method_reference"
        elif callback.get("op") == "lambda":
            params = callback.get("parameters",[]); ranges = callback.get("parameterRanges",[])
            if len(params)!=1 or len(ranges)!=1: return None
            p=params[0]; tokens = p if isinstance(p,list) else [p.get("name")] if isinstance(p,dict) and p.get("op")=="reference" else []
            if not tokens or any(not isinstance(t,str) for t in tokens): return None
            parameter=tokens[-1]; parameter_range=ranges[0]
            if len(tokens)>1:
                raw="".join(tokens[:-1]); form="explicitly_typed_expression_lambda"
            else:
                raw=expected or _explicit_input_type(callee,name); form="receiver_typed_expression_lambda"
            body=callback.get("body",{}); body_callee=body.get("callee",{})
            if (body.get("op")!="call" or body.get("arguments")!=[] or body_callee.get("op")!="reference"
                    or body_callee.get("typeArguments") or not body_callee.get("name","").startswith(parameter+".")):return None
            method=body_callee["name"][len(parameter)+1:]
            if "." in method:return None
        else:return None
        value_context=form=="unbound_instance_method_reference"
        if not raw or raw in {"this","super"} or value_context and callback_shadowed and callback_shadowed(raw, callback):return None
        explicit_context="typeArguments" in callee
        proof=callback_signature(raw,method,callback["sourceRange"]["charStart"],value_context,None,explicit_context)
        if not proof or expected and proof["inputType"]!=expected:return None
        suffix=name.removeprefix("thenComparing").removeprefix("comparing")
        key_type=proof["returnType"]
        if suffix not in KEY_FUNCTIONS or (key_type!=suffix.lower() if suffix else key_type not in {c["qualifiedName"] for c in COMPARABLE_TYPES}):return None
        def explicit_matches(spelling,expected_type):
            if expected_type==proof["inputType"]:
                selected=callback_signature(spelling,method,callback["sourceRange"]["charStart"],False,expected_type,explicit_context)
                return bool(selected and selected["inputType"]==expected_type and selected["returnType"]==key_type)
            resolved=type_name(spelling,False)
            return bool(resolved and resolved.get("resolution")=="resolved_static_type" and resolved.get("name")==expected_type)
        if not _explicit_arguments_valid(callee,name,proof["inputType"],key_type,explicit_matches):return None
        binding={"schemaVersion":1,"capability":"java-source-key-callback-1","callbackArgument":0,
            "callbackPointer":paths[id(callback)],"sourceRange":dict(callback["sourceRange"]),"form":form,
            "inputType":proof["inputType"],"returnType":key_type,"targetFunctionalInterface":KEY_FUNCTIONS[suffix],
            "parameterName":parameter,"parameterRange":dict(parameter_range) if parameter_range else None,"declarationEvidence":proof["declarationEvidence"],
            "sourceEvidenceIds":proof["sourceEvidenceIds"],"bindingScope":"declared_callback_signature_only",
            "runtimeDispatch":"UNKNOWN","bodyExecution":"UNKNOWN","javaTypeCheckSuccess":"UNKNOWN"}
        callback["staticType"]=_type(KEY_FUNCTIONS[suffix],proof["sourceEvidenceIds"],"source_callback_functional_target")
        return binding
    def lookup(function, *args):
        return platform_projection.call(function, *args) if platform_projection else function(*args)
    def visit(node):
        if node_scope is not None and isinstance(node, dict) and node.get("op") in {"lambda", "call"}:
            return node_scope(node, lambda: visit_scoped(node))
        return visit_scoped(node)

    def visit_scoped(node):
        if not isinstance(node, dict):
            return None
        op = node.get("op")
        typed = None
        if op == "reference":
            typed = lookup(reference_type, node["name"])
            if typed and "fieldBinding" in typed:
                typed = dict(typed)
                node["staticFieldBinding"] = typed.pop("fieldBinding")
            if typed is None:
                constants = {BD: {"ZERO", "ONE", "TEN"}, RM: ROUNDINGS,
                             MC: {"DECIMAL32", "DECIMAL64", "DECIMAL128", "UNLIMITED"}, DURATION: {"ZERO"},
                             TIME_UNIT: set(TIME_UNITS)}
                owner, member, imported = None, None, None
                if "." in node["name"]:
                    head, member = node["name"].rsplit(".", 1)
                    owner = lookup(type_name, head, True)
                elif static_import is not None:
                    imported = lookup(static_import, node["name"], constants)
                    if imported:
                        owner, member = imported, node["name"]
                if owner and member in constants.get(owner["name"], set()):
                    node["constantOwnerStaticType"] = owner
                    typed = _type(owner["name"], owner["sourceEvidenceIds"] + [fragment_id], "standard_named_constant", owner)
                    node["standardConstant"] = {"declaringType": owner["name"], "member": member,
                        "specification": DOC_ROOT + owner["name"].replace(".", "/") + ".html#" + member}
                    if imported:
                        node["standardConstant"]["sourceImport"] = imported["sourceImport"]
                    if owner["name"] == RM:
                        node["standardConstant"]["roundingRule"] = ROUNDING_RULES[member]
                    elif owner["name"] == BD:
                        node["standardConstant"].update(value={"ZERO": 0, "ONE": 1, "TEN": 10}[member], scale=0)
                    elif owner["name"] == MC:
                        node["standardConstant"].update(precision={"DECIMAL32": 7, "DECIMAL64": 16, "DECIMAL128": 34, "UNLIMITED": 0}[member],
                            roundingMode="HALF_UP" if member == "UNLIMITED" else "HALF_EVEN")
                    elif owner["name"] == TIME_UNIT:
                        node["standardConstant"]["nanosecondsPerUnit"] = TIME_UNITS[member]
        elif op == "literal":
            if node.get("type") == "decimal" and node.get("binding") == BD + ".String":
                typed = lookup(type_name, BD, False)
            elif node.get("type") == "string" and isinstance(node.get("literalReview"), dict):
                typed = _type("java.lang.String", [fragment_id], "reviewed_java_string_literal_type")
            elif node.get("type") in {"integer", "floating", "boolean"}:
                suffix = (node.get("javaSuffix") or "").lower()
                name = "boolean" if node["type"] == "boolean" else "float" if suffix == "f" else "double" if node["type"] == "floating" else "long" if suffix == "l" else "int"
                # An unsuffixed out-of-range integer is not a valid int literal.
                if name != "int" or int(node["value"]) <= 2147483647:
                    typed = _type(name, [fragment_id], "java_literal_type")
        elif op == "construct":
            args = [visit(arg) for arg in node.get("arguments", [])]
            owner = lookup(type_name, node["type"], False)
            # A source constructor type alone does not prove that an overload
            # exists. Unregistered/custom constructors keep UNKNOWN.
            if owner and owner["name"] == BD and "anonymousBody" not in node and all(args):
                node["constructorStaticType"] = owner
                parameters=_constructor_parameters(owner['name'],[arg['name'] for arg in args])
                if parameters is not None:
                    typed = _type(BD, owner["sourceEvidenceIds"] + [fragment_id], "standard_constructor_signature", owner, *args)
                    node["staticConstructorBinding"] = {"signature": BD + "#<init>(" + ",".join(parameters) + ")",
                        "scope": "declared_constructor_return_type", "executionSuccess": "UNKNOWN"}
        elif op == "cast":
            visit(node.get("operand"))
            typed = lookup(type_name, node.get("type", ""), False)
        elif op == "unary":
            operand = visit(node.get("operand"))
            if (operand and operand["name"] in NUMERIC and node.get("operator") in {"+", "-", "~"}
                    and (node.get("operator") != "~" or operand["name"] not in {"float", "double"})):
                typed = _type("int" if operand["name"] in {"byte", "short", "char"} else operand["name"], operand["sourceEvidenceIds"], "java_unary_numeric_promotion", operand)
            elif operand and operand["name"] == "boolean" and node.get("operator") == "!":
                typed = _type("boolean", operand["sourceEvidenceIds"], "java_boolean_negation", operand)
        elif op == "binary":
            left, right = visit(node.get("left")), visit(node.get("right"))
            if left and right:
                operator = node.get("operator")
                evidence = left["sourceEvidenceIds"] + right["sourceEvidenceIds"]
                if operator in {"==", "!=", "<", "<=", ">", ">="} and left["name"] in NUMERIC and right["name"] in NUMERIC:
                    typed = _type("boolean", evidence, "java_numeric_comparison", left, right)
                elif operator in {"+", "-", "*", "/", "%"} and left["name"] in NUMERIC and right["name"] in NUMERIC:
                    name = next((t for t in ("double", "float", "long") if t in {left["name"], right["name"]}), "int")
                    typed = _type(name, evidence, "java_binary_numeric_promotion", left, right)
        elif op == "call":
            args = [visit(arg) for arg in node.get("arguments", [])]
            callee = node.get("callee", {})
            receiver, owner, static, name = None, None, False, None
            if callee.get("op") == "member":
                receiver = visit(callee.get("receiver")); owner = receiver; name = callee["name"]
            elif callee.get("op") == "reference" and "." in callee.get("name", ""):
                head, name = callee["name"].rsplit(".", 1)
                receiver_node = {"op": "reference", "name": head}
                receiver = visit(receiver_node)
                if receiver:
                    owner = receiver
                    callee["receiverStaticType"] = receiver
                    if "standardConstant" in receiver_node:
                        callee["receiverStandardConstant"] = receiver_node["standardConstant"]
                    if "staticFieldBinding" in receiver_node:
                        callee["receiverStaticFieldBinding"] = receiver_node["staticFieldBinding"]
                    if "constantOwnerStaticType" in receiver_node:
                        callee["receiverConstantOwnerStaticType"] = receiver_node["constantOwnerStaticType"]
                else:
                    owner = lookup(type_name, head, True); static = owner is not None
                    if owner: callee["ownerStaticType"] = owner
            entry = _overload(owner["name"], name, static, args) if owner else None
            callback_binding = None
            ordering = None
            receiver_node = callee.get("receiver") if callee.get("op")=="member" else None
            receiver_order = (receiver_node or {}).get("staticContract",{}).get("orderingContract")
            if owner and owner["name"]==COMPARATOR:
                entry=None
                if name=="reversed" and not static and not args and receiver_order and "typeArguments" not in callee:
                    ordering=_ordering(node,paths[id(node)],receiver_node,paths[id(receiver_node)],None,[])
                    entry=_overload(COMPARATOR,name,False,[])
                elif (name in {"comparing"+s for s in KEY_FUNCTIONS} and static
                        or name in {"thenComparing"+s for s in KEY_FUNCTIONS} and not static and receiver_order) and len(args)==1:
                    callback_binding=callback_proof(node["arguments"][0],callee,name,receiver_order)
                    if callback_binding:
                        args=[node["arguments"][0]["staticType"]]
                        entry=_overload(COMPARATOR,name,static,args)
                        ordering=_ordering(node,paths[id(node)],receiver_node,paths.get(id(receiver_node)),callback_binding,[])
                if ordering and (len(ordering["keys"])>16 or any(len(k["reversalCallPointers"])>16 for k in ordering["keys"])):
                    entry=None;ordering=None;callback_binding=None
            if owner and owner["name"]==RESPONSE and name=="status" and len(args)==1:
                arg=node["arguments"][0]
                if not _status_argument_admitted(arg,fragment_id):entry=None
            if owner and owner["name"] == FUTURE and not static and name in {"whenComplete", "thenApply"}:
                formal, arity = (BICONSUMER, 2) if name == "whenComplete" else (FUNCTION, 1)
                callback = node.get("arguments", [None])[0] if len(args) == 1 else None
                if isinstance(callback, dict) and callback.get("op") == "lambda":
                    parameters = callback.get("parameters", [])
                    names = [p.get("name") if isinstance(p, dict) and p.get("op") == "reference" else
                             p[0] if isinstance(p, list) and len(p) == 1 else None for p in parameters]
                    if len(names) == arity and all(names) and len(set(names)) == arity:
                        args = [_type(formal, [fragment_id], "unique_standard_method_lambda_target")]
                        callback_binding = {"basis": "unique_standard_method_and_lambda_arity", "arity": arity,
                            "targetFunctionalInterface": formal, "genericTypes": "UNKNOWN", "bodyTypeCheck": "UNKNOWN",
                            "bodyExecution": "UNKNOWN", "callbackArgument": 0}
                        if callback.get("body", {}).get("op") == "body_reference":
                            callback_binding["bodyId"] = callback["body"]["bodyId"]
                        entry = _overload(owner["name"], name, False, args)
                    else:
                        entry = None
                elif entry:
                    receiver_args = owner.get("typeArguments", [])
                    function_args = args[0].get("typeArguments", [])
                    raw = owner.get("typeArgumentsStatus") == args[0].get("typeArgumentsStatus") == "raw"
                    compatible = (len(receiver_args) == 1 and len(function_args) == 2
                        and function_args[0] in {receiver_args[0], "java.lang.Object"}
                        and (name == "thenApply" or function_args[1] in {"java.lang.Throwable", "java.lang.Object"}))
                    if not (raw or compatible):
                        entry = None
                    else:
                        callback_binding = {"basis": "declared_functional_interface", "callbackArgument": 0,
                            "targetFunctionalInterface": formal, "genericTypes": "raw_unchecked" if raw else "resolved",
                            "bodyExecution": "UNKNOWN"}
            if entry:
                owner_name = owner["name"]
                signature = owner_name + "#" + name + "(" + ",".join(entry["parameters"]) + "):" + entry["returnType"]
                evidence = owner["sourceEvidenceIds"] + [fragment_id]
                for arg in args: evidence.extend(arg["sourceEvidenceIds"])
                # The result points to this source fragment, whose operand
                # bindings retain the original symbols. Do not recursively
                # duplicate all ancestor evidence on every link of a chain.
                typed = _type(entry["returnType"], [fragment_id], "standard_api_return_signature", owner, *args)
                if owner_name == FUTURE and name in {"whenComplete", "thenApply"}:
                    result_arguments = owner.get("typeArguments", []) if name == "whenComplete" else args[0].get("typeArguments", [])[1:2]
                    typed.update(typeArguments=result_arguments, typeArgumentsStatus="resolved" if result_arguments else "UNKNOWN")
                    typed["sourceStageIdentity"] = {"id": "stage:" + hashlib.sha256((fragment_id + ":" + str(node.get("sourceInvocationOffset"))).encode()).hexdigest(),
                        "kind": "call_result", "runtimeObjectIdentity": "UNKNOWN"}
                operands = [{"role": "argument", "argumentIndex": i, "actualType": arg["name"], "formalType": formal,
                             "sourceEvidenceIds": arg["sourceEvidenceIds"]} for i, (arg, formal) in enumerate(zip(args, entry["parameters"]))]
                for operand in operands:
                    if (operand["actualType"], operand["formalType"]) == (INSTANT, TEMPORAL):
                        operand["conversion"] = {"kind": "widening_reference", "basis": "documented_platform_interface",
                            "specification": DOC_ROOT + "java/time/Instant.html"}
                if receiver: operands.insert(0, {"role": "receiver", "actualType": receiver["name"], "sourceEvidenceIds": receiver["sourceEvidenceIds"]})
                catalog_entry = _catalog_entry(owner_name, name, static, entry)
                contract_id = catalog_entry["id"]
                catalog[contract_id] = catalog_entry
                node["staticContract"] = {"contractId": contract_id, "operands": operands,
                    "sourceEvidenceIds": sorted(set(evidence)), "catalogLocation": "fragment.standardApiContracts"}
                policy_java_platform.inherit(node["staticContract"], owner, *args)
                if ordering:
                    ordering["sourceEvidenceIds"]=sorted(set(evidence))
                    node["staticContract"]["orderingContract"]=ordering
                    typed.update(typeArguments=[ordering["inputType"]],typeArgumentsStatus="resolved")
                    if callback_binding:node["staticContract"]["callbackBinding"]=callback_binding
                elif callback_binding:
                    node["staticContract"]["callbackBinding"] = callback_binding
                    if callback_binding["basis"] == "unique_standard_method_and_lambda_arity":
                        node["staticContract"]["operands"][-1]["actualTypeStatus"] = "target_type_only_body_compatibility_unknown"
                    node["staticContract"]["stageRelation"] = {"receiver": owner.get("sourceStageIdentity", {"kind": "source_expression", "runtimeObjectIdentity": "UNKNOWN"}),
                        "dependent": typed["sourceStageIdentity"], "relation": "new_dependent_stage_on_success",
                        "runtimeAliasAnalysis": "UNKNOWN", "dependentCancellationDoesNotProveReceiverCancellation": True}
                elif owner_name == FUTURE and name == "cancel":
                    node["staticContract"]["stageReceiver"] = owner.get("sourceStageIdentity", {"kind": "source_expression", "runtimeObjectIdentity": "UNKNOWN"})
                if owner_name.startswith("org.springframework.http."):
                    status_contract=_response_contract(node,paths[id(node)],receiver_node,paths,evidence)
                    node["staticContract"]["responseStatusContract"]=status_contract
                    if owner_name==BODY and name=="build":
                        node["staticContract"]["receiverBridge"]=_receiver_bridge(owner,catalog_entry)
            else:
                typed = lookup(call_result, node.get("sourceInvocationOffset"))
                if typed is None and receiver and record_call_result is not None:
                    typed = lookup(record_call_result, receiver, name, len(args), node.get("sourceInvocationOffset"))
                if typed is None and record_accessor is not None and receiver:
                    accessor = lookup(record_accessor, receiver, name, len(args), node.get("sourceInvocationOffset"))
                    if accessor:
                        node["accessorReturnStaticType"] = accessor["resultType"]
                        typed = {**accessor["resultType"], **_type(accessor["resultType"]["name"],
                            accessor["resultType"]["sourceEvidenceIds"], "record_accessor_result",
                            accessor["resultType"], receiver)}
                        node["staticAccessorBinding"] = accessor["binding"]
                node["staticContractStatus"] = {"status": "UNKNOWN", "reason": "callback_type_or_shape_not_proven" if owner and owner["name"] == FUTURE and name in {"whenComplete", "thenApply"} else "receiver_type_or_overload_not_proven"}
                if owner and owner["name"]==RESPONSE and name=="status" and len(node.get("arguments",[]))==1:
                    node["staticContractStatus"]["statusArgument"]={"schemaVersion":1,"capability":"spring-response-status-1",
                        "argumentIndex":0,"argumentPointer":paths[id(node)]+"/arguments/0","value":"UNKNOWN"}
        elif op == "conditional":
            visit(node.get("condition")); yes, no = visit(node.get("then")), visit(node.get("else"))
            if yes and no and yes["name"] == no["name"]:
                typed = _type(yes["name"], yes["sourceEvidenceIds"] + no["sourceEvidenceIds"], "identical_conditional_operand_types", yes, no)
        elif op == "lambda":
            # Parent integration already suppresses all names shadowed by a
            # nested lambda; no lambda parameter inference is attempted here.
            visit(node.get("body"))
        else:
            for value in node.values():
                if isinstance(value, dict): visit(value)
                elif isinstance(value, list):
                    for item in value: visit(item)
        if typed is not None:
            node["staticType"] = typed
        return typed

    visit(expression)
    return list(catalog.values())


validate_catalog_entry.validate_composition = validate_composition
