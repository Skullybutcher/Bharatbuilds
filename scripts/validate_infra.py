"""Local AWS-IaC validation (no credentials needed).

Checks: template.yaml parses + required resources/policies/substitutions;
statemachine.asl.json parses + state graph integrity + handler existence;
dashboard JSON parses. Run: make infra-validate
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"
ok = True


def check(name, cond, detail=""):
    global ok
    print(f"  {'PASS' if cond else 'FAIL'} {name} {detail if not cond else ''}")
    if not cond:
        ok = False


def main():
    import yaml

    class CfnLoader(yaml.SafeLoader):
        pass

    def _cfn(loader, tag_suffix, node):
        if isinstance(node, yaml.ScalarNode):
            return {tag_suffix: loader.construct_scalar(node)}
        if isinstance(node, yaml.SequenceNode):
            return {tag_suffix: loader.construct_sequence(node)}
        return {tag_suffix: loader.construct_mapping(node)}

    for tag in ("Ref", "Sub", "GetAtt", "Join", "Select", "If", "Equals",
                "FindInMap", "ImportValue", "Transform"):
        CfnLoader.add_constructor(f"!{tag}", lambda l, n, t=tag: _cfn(l, t, n))
    CfnLoader.add_multi_constructor("!", lambda l, s, n: _cfn(l, s, n))
    tpl = yaml.load((INFRA / "template.yaml").read_text(), Loader=CfnLoader)
    res = tpl.get("Resources", {})
    for name in ("SourceBucket", "ArtifactBucket", "RegistryTable", "Api", "ApiFn",
                 "ExtractorFn", "CompilerFn", "WitnessFn", "ValidatorFn", "ImpactFn",
                 "GovernFn", "BuildStateMachine", "StateMachineLogs", "NewPolicyEventRule",
                 "EventBridgeToSfnRole", "ExecutionsFailedAlarm", "FunctionErrorsAlarm",
                 "Dashboard", "FrontendApp", "FrontendBranch"):
        check(f"resource {name}", name in res)
    tbl = res["RegistryTable"]["Properties"]
    check("dynamodb on-demand", tbl.get("BillingMode") == "PAY_PER_REQUEST")
    check("dynamodb PITR", tbl["PointInTimeRecoverySpecification"]["PointInTimeRecoveryEnabled"] is True)
    check("GSI1 for idempotency", any(i["IndexName"] == "GSI1" for i in tbl["GlobalSecondaryIndexes"]))
    check("source bucket private", res["SourceBucket"]["Properties"]["PublicAccessBlockConfiguration"]["BlockPublicAcls"] is True)
    check("source bucket versioned", res["SourceBucket"]["Properties"]["VersioningConfiguration"]["Status"] == "Enabled")
    check("source bucket eventbridge", res["SourceBucket"]["Properties"]["NotificationConfiguration"]["EventBridgeConfiguration"]["EventBridgeEnabled"] is True)
    check("storage=dynamodb env", "PROCESSPATCH_STORAGE" in str(tpl))
    for fn in ("ApiFn", "ExtractorFn", "CompilerFn", "WitnessFn", "ValidatorFn", "ImpactFn", "GovernFn"):
        h = res[fn]["Properties"]["Handler"]
        mod, func = h.rsplit(".", 1)
        mod = mod.replace(".", "/") + ".py"
        check(f"handler file {h}", (ROOT / mod).exists())
        check(f"handler fn {func}", f"def {func}(" in (ROOT / mod).read_text())
    subs = res["BuildStateMachine"]["Properties"]["DefinitionSubstitutions"]
    asl_raw = (INFRA / "statemachine.asl.json").read_text()
    for k in subs:
        check(f"ASL substitution {k}", "${" + k + "}" in asl_raw)
    check("sfn logging", "Logging" in res["BuildStateMachine"]["Properties"])
    check("sfn tracing", res["BuildStateMachine"]["Properties"].get("Tracing", {}).get("Enabled") is True)

    sm = json.loads(asl_raw)
    states = sm["States"]
    check("asl StartAt exists", sm["StartAt"] in states)
    # graph walk: every Next/Choice target + Default must exist; terminals checked
    refs = set()
    for name, st in states.items():
        if "Next" in st:
            refs.add(st["Next"])
        if st.get("Type") == "Choice":
            for c in st.get("Choices", []):
                refs.add(c["Next"])
            if "Default" in st:
                refs.add(st["Default"])
    check("asl all refs resolve", refs <= set(states), str(refs - set(states)))
    terms = [n for n, s in states.items() if s.get("Type") in ("Succeed", "Fail") or s.get("End")]
    check("asl has terminals", len(terms) >= 3, str(terms))
    gov = [n for n in states if "APPROVAL" in n or "REVIEW" in n or "ACTIVAT" in n]
    check("asl governance gates", len(gov) >= 6, str(gov))
    tokens = sum("waitForTaskToken" in json.dumps(s) for s in states.values())
    check("asl task-token waits", tokens >= 3, str(tokens))
    fns = re.findall(r"\$\{(\w+FnArn)\}", asl_raw)
    check("asl fn refs subset of substitutions", set(fns) <= set(subs), str(set(fns) - set(subs)))

    dash = json.loads((INFRA / "cloudwatch-dashboard.json").read_text())
    check("dashboard widgets", len(dash.get("widgets", [])) >= 5)
    check("dashboard custom namespace", "ProcessPatch" in json.dumps(dash))

    for f in ("deploy.sh", "deploy.ps1"):
        check(f"deploy script {f}", (INFRA / f).exists())
    check("parameters.json", (INFRA / "parameters.json").exists())
    print("INFRA-VALIDATE", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
