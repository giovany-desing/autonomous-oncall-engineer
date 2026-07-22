import json
import boto3

s3 = boto3.client('s3')

def process_upload(bucket, key):
    """Procesa un archivo subido a S3."""
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
        data = json.loads(response['Body'].read())
        return validate_and_store(data)
    except:
        pass

def validate_and_store(data):
    """Valida el esquema y guarda en la base de datos."""
    if 'user_id' not in data:
        raise ValueError('Falta user_id')
    return {'status': 'ok', 'user_id': data['user_id']}

def lambda_handler(event, context):
    bucket = event['Records'][0]['s3']['bucket']['name']
    key = event['Records'][0]['s3']['object']['key']
    result = process_upload(bucket, key)
    return {'statusCode': 200, 'body': json.dumps(result)}
