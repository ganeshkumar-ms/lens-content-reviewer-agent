import io
import json
import mimetypes
import os
import sys
import time
import zipfile
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import boto3
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / 'backend' / '.env')
load_dotenv()

REGION = 'us-east-1'
sts = boto3.client('sts', region_name=REGION)
ACCOUNT_ID = sts.get_caller_identity()['Account']
BUCKET_NAME = f'lens-ui-{ACCOUNT_ID}'
ROLE_NAME = 'lens-backend-lambda-role'
LAMBDA_NAME = 'lens-backend-api'
API_NAME = 'lens-http-api'

s3 = boto3.client('s3', region_name=REGION)
iam = boto3.client('iam', region_name=REGION)
lam = boto3.client('lambda', region_name=REGION)
apigw = boto3.client('apigatewayv2', region_name=REGION)
cf = boto3.client('cloudfront', region_name=REGION)


def step1_s3_and_upload():
    print(f'1. Ensuring S3 bucket {BUCKET_NAME} exists...')
    try:
        s3.head_bucket(Bucket=BUCKET_NAME)
    except Exception:
        s3.create_bucket(Bucket=BUCKET_NAME)

    s3.put_public_access_block(
        Bucket=BUCKET_NAME,
        PublicAccessBlockConfiguration={
            'BlockPublicAcls': True,
            'IgnorePublicAcls': True,
            'BlockPublicPolicy': True,
            'RestrictPublicBuckets': True,
        },
    )

    s3.put_bucket_cors(
        Bucket=BUCKET_NAME,
        CORSConfiguration={
            'CORSRules': [
                {
                    'AllowedHeaders': ['*'],
                    'AllowedMethods': ['GET', 'PUT', 'POST', 'HEAD'],
                    'AllowedOrigins': ['*'],
                    'ExposeHeaders': ['ETag'],
                    'MaxAgeSeconds': 3600,
                }
            ]
        },
    )

    dist_dir = BASE_DIR / 'frontend' / 'dist'
    if not dist_dir.exists():
        print('   Frontend dist folder not found! Build frontend first.')
        return

    for file_path in dist_dir.rglob('*'):
        if file_path.is_file():
            rel = file_path.relative_to(dist_dir).as_posix()
            ctype, _ = mimetypes.guess_type(str(file_path))
            if file_path.suffix == '.js':
                ctype = 'application/javascript'
            elif file_path.suffix == '.css':
                ctype = 'text/css'
            elif file_path.suffix == '.html':
                ctype = 'text/html; charset=utf-8'
            s3.put_object(
                Bucket=BUCKET_NAME,
                Key=rel,
                Body=file_path.read_bytes(),
                ContentType=ctype or 'application/octet-stream',
            )
            print(f'   Uploaded s3://{BUCKET_NAME}/{rel} ({ctype})')


def step2_iam_role() -> str:
    print(f'2. Ensuring IAM Role {ROLE_NAME}...')
    trust = {
        'Version': '2012-10-17',
        'Statement': [{
            'Effect': 'Allow',
            'Principal': {'Service': 'lambda.amazonaws.com'},
            'Action': 'sts:AssumeRole',
        }],
    }

    try:
        role_arn = iam.get_role(RoleName=ROLE_NAME)['Role']['Arn']
    except iam.exceptions.NoSuchEntityException:
        role_arn = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
        )['Role']['Arn']
        print('   Created IAM role, waiting 10s for propagation...')
        time.sleep(10)

    for p in [
        'arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole',
        'arn:aws:iam::aws:policy/AmazonBedrockFullAccess',
        'arn:aws:iam::aws:policy/AmazonS3FullAccess',
    ]:
        try:
            iam.attach_role_policy(RoleName=ROLE_NAME, PolicyArn=p)
        except Exception:
            pass
    return role_arn


def build_lambda_zip() -> bytes:
    print('3. Packaging Lambda deployment zip...')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        backend_dir = BASE_DIR / 'backend'
        for root, dirs, files in os.walk(backend_dir):
            if any(skip in root for skip in ['venv', '__pycache__', '.git', 'uploads']):
                continue
            for f in files:
                if f.endswith('.pyc') or f.endswith('.env'):
                    continue
                full_path = Path(root) / f
                rel_path = full_path.relative_to(backend_dir).as_posix()
                z.write(full_path, rel_path)
    return buf.getvalue()


def step3_lambda(role_arn: str) -> str:
    print(f'4. Deploying Lambda function {LAMBDA_NAME}...')
    zip_bytes = build_lambda_zip()
    env_vars = {
        'Variables': {
            'LENS_S3_BUCKET': BUCKET_NAME,
        }
    }

    try:
        fn = lam.get_function(FunctionName=LAMBDA_NAME)
        lam.update_function_code(FunctionName=LAMBDA_NAME, ZipFile=zip_bytes)
        time.sleep(4)
        lam.update_function_configuration(
            FunctionName=LAMBDA_NAME,
            Timeout=120,
            MemorySize=512,
            Environment=env_vars,
        )
        arn = fn['Configuration']['FunctionArn']
        print(f'   Updated existing Lambda: {arn}')
    except lam.exceptions.ResourceNotFoundException:
        fn = lam.create_function(
            FunctionName=LAMBDA_NAME,
            Runtime='python3.11',
            Role=role_arn,
            Handler='lambda_function.lambda_handler',
            Code={'ZipFile': zip_bytes},
            Timeout=120,
            MemorySize=512,
            Environment=env_vars,
        )
        arn = fn['FunctionArn']
        print(f'   Created Lambda: {arn}')
    return arn


def step4_api_gateway(lambda_arn: str) -> tuple:
    print(f'5. Configuring HTTP API Gateway {API_NAME}...')
    apis = apigw.get_apis()['Items']
    api_id = None
    for a in apis:
        if a['Name'] == API_NAME:
            api_id = a['ApiId']
            break

    if not api_id:
        res = apigw.create_api(
            Name=API_NAME,
            ProtocolType='HTTP',
            CorsConfiguration={
                'AllowOrigins': ['*'],
                'AllowMethods': ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
                'AllowHeaders': ['*'],
            },
        )
        api_id = res['ApiId']
        print(f'   Created API Gateway: {api_id}')

    int_uri = f'arn:aws:apigateway:{REGION}:lambda:path/2015-03-31/functions/{lambda_arn}/invocations'
    ints = apigw.get_integrations(ApiId=api_id)['Items']
    int_id = None
    for i in ints:
        if i.get('IntegrationUri') == int_uri:
            int_id = i['IntegrationId']
            break

    if not int_id:
        res = apigw.create_integration(
            ApiId=api_id,
            IntegrationType='AWS_PROXY',
            IntegrationUri=int_uri,
            PayloadFormatVersion='2.0',
        )
        int_id = res['IntegrationId']

    routes = apigw.get_routes(ApiId=api_id)['Items']
    route_keys = {r['RouteKey'] for r in routes}
    target = f'integrations/{int_id}'

    for rk in ['ANY /{proxy+}', 'GET /health', 'POST /api/review']:
        if rk not in route_keys:
            try:
                apigw.create_route(ApiId=api_id, RouteKey=rk, Target=target)
            except Exception:
                pass

    try:
        apigw.get_stage(ApiId=api_id, StageName='$default')
    except apigw.exceptions.NotFoundException:
        apigw.create_stage(ApiId=api_id, StageName='$default', AutoDeploy=True)

    try:
        lam.add_permission(
            FunctionName=LAMBDA_NAME,
            StatementId=f'apigw-invoke-{api_id}',
            Action='lambda:InvokeFunction',
            Principal='apigateway.amazonaws.com',
            SourceArn=f'arn:aws:execute-api:{REGION}:{ACCOUNT_ID}:{api_id}/*/*',
        )
    except lam.exceptions.ResourceConflictException:
        pass

    api_endpoint = f'https://{api_id}.execute-api.{REGION}.amazonaws.com'
    print(f'   API Gateway ready: {api_endpoint}')
    return api_id, api_endpoint


def step5_cloudfront(api_id: str):
    print('6. Configuring CloudFront Distribution with OAC...')
    s3_origin_id = f'S3-{BUCKET_NAME}'
    s3_domain = f'{BUCKET_NAME}.s3.{REGION}.amazonaws.com'
    api_origin_id = f'API-{api_id}'
    api_domain = f'{api_id}.execute-api.{REGION}.amazonaws.com'

    oac_name = f'lens-oac-{ACCOUNT_ID}'
    oac_id = None
    try:
        for o in cf.list_origin_access_controls()['OriginAccessControlList'].get('Items', []):
            if o['Name'] == oac_name:
                oac_id = o['Id']
                break
    except Exception:
        pass

    if not oac_id:
        oac_res = cf.create_origin_access_control(
            OriginAccessControlConfig={
                'Name': oac_name,
                'Description': 'OAC for LENS UI S3 Bucket',
                'SigningProtocol': 'sigv4',
                'SigningBehavior': 'always',
                'OriginAccessControlOriginType': 's3',
            }
        )
        oac_id = oac_res['OriginAccessControl']['Id']

    policy = {
        'Version': '2012-10-17',
        'Statement': [
            {
                'Sid': 'AllowCloudFrontServicePrincipalReadOnly',
                'Effect': 'Allow',
                'Principal': {'Service': 'cloudfront.amazonaws.com'},
                'Action': 's3:GetObject',
                'Resource': f'arn:aws:s3:::{BUCKET_NAME}/*',
                'Condition': {
                    'StringEquals': {
                        'AWS:SourceArn': f'arn:aws:cloudfront::{ACCOUNT_ID}:distribution/*'
                    }
                },
            }
        ],
    }
    s3.put_bucket_policy(Bucket=BUCKET_NAME, Policy=json.dumps(policy))

    dists = cf.list_distributions().get('DistributionList', {}).get('Items', [])
    dist_id = None
    domain_name = None

    for d in dists:
        for orig in d['Origins']['Items']:
            if orig['DomainName'] == s3_domain:
                dist_id = d['Id']
                domain_name = d['DomainName']
                break
        if dist_id:
            break

    dist_config = {
        'CallerReference': str(time.time()),
        'Comment': 'LENS Content Reviewer & Consistency Auditor UI + API',
        'Enabled': True,
        'DefaultRootObject': 'index.html',
        'Origins': {
            'Quantity': 2,
            'Items': [
                {
                    'Id': s3_origin_id,
                    'DomainName': s3_domain,
                    'OriginAccessControlId': oac_id,
                    'S3OriginConfig': {'OriginAccessIdentity': ''},
                },
                {
                    'Id': api_origin_id,
                    'DomainName': api_domain,
                    'CustomOriginConfig': {
                        'HTTPPort': 80,
                        'HTTPSPort': 443,
                        'OriginProtocolPolicy': 'https-only',
                        'OriginSslProtocols': {'Quantity': 1, 'Items': ['TLSv1.2']},
                    },
                },
            ],
        },
        'DefaultCacheBehavior': {
            'TargetOriginId': s3_origin_id,
            'ViewerProtocolPolicy': 'redirect-to-https',
            'AllowedMethods': {
                'Quantity': 2,
                'Items': ['GET', 'HEAD'],
                'CachedMethods': {'Quantity': 2, 'Items': ['GET', 'HEAD']},
            },
            'ForwardedValues': {
                'QueryString': False,
                'Cookies': {'Forward': 'none'},
            },
            'MinTTL': 0,
            'DefaultTTL': 86400,
            'MaxTTL': 31536000,
        },
        'CacheBehaviors': {
            'Quantity': 1,
            'Items': [
                {
                    'PathPattern': '/api/*',
                    'TargetOriginId': api_origin_id,
                    'ViewerProtocolPolicy': 'redirect-to-https',
                    'AllowedMethods': {
                        'Quantity': 7,
                        'Items': ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'OPTIONS', 'DELETE'],
                        'CachedMethods': {'Quantity': 2, 'Items': ['GET', 'HEAD']},
                    },
                    'Compress': True,
                    'CachePolicyId': '4135ea2d-6df8-44a3-9df3-4b5a84be39ad',
                    'OriginRequestPolicyId': 'b689b0a8-53d0-40ab-baf2-68738e2966ac',
                }
            ],
        },
        'CustomErrorResponses': {
            'Quantity': 1,
            'Items': [
                {
                    'ErrorCode': 403,
                    'ResponsePagePath': '/index.html',
                    'ResponseCode': '200',
                    'ErrorCachingMinTTL': 0,
                }
            ],
        },
    }

    if not dist_id:
        print('   Creating new CloudFront distribution...')
        res = cf.create_distribution(DistributionConfig=dist_config)
        dist_id = res['Distribution']['Id']
        domain_name = res['Distribution']['DomainName']
        dist_arn = res['Distribution']['ARN']
    else:
        print(f'   CloudFront distribution exists: {dist_id}')
        dist_arn = f'arn:aws:cloudfront::{ACCOUNT_ID}:distribution/{dist_id}'

    # Update S3 bucket policy to allow this specific CloudFront distribution ARN
    bucket_policy = {
        'Version': '2012-10-17',
        'Statement': [
            {
                'Sid': 'AllowCloudFrontServicePrincipalReadOnly',
                'Effect': 'Allow',
                'Principal': {'Service': 'cloudfront.amazonaws.com'},
                'Action': 's3:GetObject',
                'Resource': f'arn:aws:s3:::{BUCKET_NAME}/*',
                'Condition': {
                    'StringEquals': {
                        'AWS:SourceArn': dist_arn
                    }
                },
            }
        ],
    }
    s3.put_bucket_policy(Bucket=BUCKET_NAME, Policy=json.dumps(bucket_policy))

    # Invalidate cache
    try:
        cf.create_invalidation(
            DistributionId=dist_id,
            InvalidationBatch={
                'Paths': {'Quantity': 1, 'Items': ['/*']},
                'CallerReference': str(time.time()),
            },
        )
        print('   CloudFront cache invalidation triggered.')
    except Exception:
        pass

    print(f'\n======================================================')
    print(f' LENS DEPLOYMENT COMPLETE')
    print(f' CloudFront URL: https://{domain_name}')
    print(f' API Gateway:    https://{api_id}.execute-api.{REGION}.amazonaws.com')
    print(f' S3 Bucket:      s3://{BUCKET_NAME}')
    print(f' Lambda:         {LAMBDA_NAME}')
    print(f'======================================================')
    return domain_name, f'https://{api_id}.execute-api.{REGION}.amazonaws.com'


def build_frontend_for_production(api_endpoint: str):
    print(f'Setting VITE_API_BASE to {api_endpoint} in .env.production...')
    prod_env = BASE_DIR / 'frontend' / '.env.production'
    prod_env.write_text(f'VITE_API_BASE={api_endpoint}\n', encoding='utf-8')
    print('Rebuilding frontend with production environment...')
    import subprocess
    cmd = 'cd /d "' + str(BASE_DIR / 'frontend') + '" && npm run build'
    res = subprocess.run(f'cmd.exe /c "{cmd}"', shell=True, capture_output=True, text=True)
    if res.returncode != 0:
        print('Build failed:', res.stderr)
        raise RuntimeError('Frontend build failed')
    print('Production build completed successfully.')


def main():
    print(f'Starting LENS deployment on AWS Account {ACCOUNT_ID} ({REGION})...')
    # 1. IAM Role & Lambda
    role_arn = step2_iam_role()
    lambda_arn = step3_lambda(role_arn)
    api_id, api_endpoint = step4_api_gateway(lambda_arn)

    # 2. Build frontend with API Gateway URL
    build_frontend_for_production(api_endpoint)

    # 3. Upload built dist to S3
    step1_s3_and_upload()

    # 4. Configure CloudFront distribution
    cf_domain, _ = step5_cloudfront(api_id)
    return cf_domain, api_endpoint


if __name__ == '__main__':
    main()
