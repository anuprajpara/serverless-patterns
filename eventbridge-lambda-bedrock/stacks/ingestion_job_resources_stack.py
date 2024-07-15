from aws_cdk import (
    Duration,
    Stack,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_scheduler as scheduler,
    aws_sqs as sqs,
    aws_logs as logs,
)
from constructs import Construct

class IngestionJobResourcesStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, stack_suffix,
                 knowledge_base_id, 
                 data_source_id, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        admin_role_name = self.node.try_get_context('admin_role_name')
        admin_role_arn = f"arn:aws:iam::{self.account}:role/{admin_role_name}"
        
        dead_letter_queue = sqs.Queue(
            self, "BedrockKBDataSourceSyncDLQ",
            queue_name=f"BedrockKBDatSourceSyncDLQ-{stack_suffix}",
            retention_period=Duration.days(14),
            visibility_timeout=Duration.seconds(120),
        )
        dead_letter_queue.add_to_resource_policy(
            iam.PolicyStatement(
                actions=["sqs:*"],
                effect=iam.Effect.ALLOW,
                resources=[dead_letter_queue.queue_arn],
                principals=[iam.ArnPrincipal(
                    admin_role_arn
                )]
            )   
        )
        dead_letter_queue.add_to_resource_policy(
            iam.PolicyStatement(
                actions=["sqs:SendMessage"],
                effect=iam.Effect.ALLOW,
                resources=[dead_letter_queue.queue_arn],
                principals=[iam.ServicePrincipal(
                    "scheduler.amazonaws.com"
                )]
            )
        )

        #Create an IAM Service Role for Bedrock Knowledge Base
        eventbridge_scheduler_role = iam.Role(self, "EventBridgeSchedulerRole",
            role_name="EventBridgeSchedulerRole",
            inline_policies={
                "BedrockKBSyncPolicy": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=["bedrock:StartIngestionJob"],
                            resources=["*"]
                        ),
                        iam.PolicyStatement(
                            actions=["sqs:SendMessage"],
                            resources=[
                                dead_letter_queue.queue_arn
                            ]
                        )
                    ]
                )
            },
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com",
                conditions={
                    "StringEquals": {
                        "aws:SourceAccount": self.account
                    }
                }
            )
        )
        
        cfn_schedule_group = scheduler.CfnScheduleGroup(self, "BedrockKBSyncScheduleGroup",
            name="BedrockKBSyncScheduleGroup"
        )
        cfn_schedule = scheduler.CfnSchedule(self, "BedrockKBDataSourceSyncSchedule",
            description="Schedule to Sync Bedrock Knowledge Base Data Source Periodically",
            name="BedrockKBDataSourceSyncSchedule",
            group_name=cfn_schedule_group.name,
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(
                mode="OFF"
            ),
            schedule_expression="rate(5 minutes)",
            schedule_expression_timezone="UTC+01:00",
            target=scheduler.CfnSchedule.TargetProperty(
                arn="arn:aws:scheduler:::aws-sdk:bedrockagent:startIngestionJob",
                role_arn=eventbridge_scheduler_role.role_arn,
                dead_letter_config = scheduler.CfnSchedule.DeadLetterConfigProperty(
                    arn=dead_letter_queue.queue_arn
                ),
                input="{\"KnowledgeBaseId\":\""+knowledge_base_id+"\",\"DataSourceId\":\""+data_source_id+"\"}"
            )
        )        
