output "lambda_function_name" {
  value = aws_lambda_function.handler.function_name
}

output "lambda_log_group" {
  value = "/aws/lambda/${aws_lambda_function.handler.function_name}"
}

output "s3_bucket_name" {
  value = aws_s3_bucket.uploads.bucket
}
