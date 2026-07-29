resource "aws_lambda_permission" "allow_cloudwatch_logs___PROJECT_SLUG__" {
  statement_id  = "AllowCloudWatchLogsInvoke__PROJECT_STATEMENT__"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.agent.function_name
  principal     = "logs.us-east-1.amazonaws.com"
  source_arn    = "arn:aws:logs:us-east-1:531728396479:log-group:__LOG_GROUP__:*"
}

resource "aws_cloudwatch_log_subscription_filter" "__PROJECT_SLUG___errors" {
  name            = "oncall-agent-error-trigger-__PROJECT_SLUG__"
  log_group_name  = "__LOG_GROUP__"
  filter_pattern  = "?ERROR ?WARNING ?\"Task timed out\""
  destination_arn = aws_lambda_function.agent.arn

  depends_on = [aws_lambda_permission.allow_cloudwatch_logs___PROJECT_SLUG__]
}
