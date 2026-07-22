"""
Adaptador de descubrimiento de infraestructura. Usa Resource Groups
Tagging API para encontrar cualquier recurso de AWS asociado a un
proyecto por tag — genérico frente al tipo de recurso y a la herramienta
de IaC usada para crearlo (Terraform, CDK, consola manual, etc.).
"""
from dataclasses import dataclass, field

import boto3


@dataclass
class TaggedResource:
    arn: str
    resource_type: str
    tags: dict = field(default_factory=dict)


@dataclass
class LambdaConfig:
    function_name: str
    runtime: str
    memory_size: int
    timeout: int
    architectures: list = field(default_factory=list)
    last_modified: str = ""


def discover_resources_by_tag(
    tag_key: str,
    tag_value: str,
    region: str,
    aws_client=None,
) -> list:
    client = aws_client or boto3.client("resourcegroupstaggingapi", region_name=region)

    resources = []
    paginator = client.get_paginator("get_resources")
    for page in paginator.paginate(
        TagFilters=[{"Key": tag_key, "Values": [tag_value]}]
    ):
        for r in page.get("ResourceTagMappingList", []):
            arn = r["ResourceARN"]
            resource_type = arn.split(":")[2]
            tags = {t["Key"]: t["Value"] for t in r.get("Tags", [])}
            resources.append(TaggedResource(arn=arn, resource_type=resource_type, tags=tags))

    return resources


def get_lambda_config(function_name: str, region: str, aws_client=None) -> LambdaConfig:
    client = aws_client or boto3.client("lambda", region_name=region)
    response = client.get_function_configuration(FunctionName=function_name)

    return LambdaConfig(
        function_name=response["FunctionName"],
        runtime=response.get("Runtime", "n/a"),
        memory_size=response["MemorySize"],
        timeout=response["Timeout"],
        architectures=response.get("Architectures", []),
        last_modified=response["LastModified"],
    )


if __name__ == "__main__":
    import sys
    import json

    tag_key = sys.argv[1] if len(sys.argv) > 1 else "oncall-project"
    tag_value = sys.argv[2] if len(sys.argv) > 2 else "rag-demo"
    region = sys.argv[3] if len(sys.argv) > 3 else "us-east-1"

    resources = discover_resources_by_tag(tag_key, tag_value, region)
    print(f"=== Recursos con tag {tag_key}={tag_value} ===")
    for r in resources:
        print(f"  [{r.resource_type}] {r.arn}")

    lambda_resources = [r for r in resources if r.resource_type == "lambda"]
    if lambda_resources:
        function_name = lambda_resources[0].arn.split(":")[-1]
        print(f"\n=== Config de Lambda: {function_name} ===")
        config = get_lambda_config(function_name, region)
        print(json.dumps(config.__dict__, indent=2, ensure_ascii=False))
