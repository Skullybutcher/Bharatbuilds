# Cost estimate (ap-south-1, demo scale)

Per canonical compile (worst case, 1M-request free tiers unused):
Lambda ~8 invocations × ~1s × 512MB ≈ $0.00001; Step Functions 40 transitions
≈ 40 × $0.000025 = $0.0010; DynamoDB on-demand ≈ $0.00001; S3 ≈ $0.000001;
Bedrock extraction (Nova Micro, ~2k tokens) ≈ $0.0001–$0.0003.
Total ≈ **$0.001 per build**, a few dollars per month at demo traffic.

Steady-state monthly floor: $0 (all serverless/on-demand; Amplify build minutes
only on push; CloudWatch dashboard $3/mo if kept, alarms negligible).
No EC2, no Neptune, no always-on anything, bursty by design (Spec §55).
