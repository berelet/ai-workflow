import os
import logging
from contextlib import asynccontextmanager

import aiobotocore.session

logger = logging.getLogger("storage.s3")

S3_BUCKET = os.getenv("S3_BUCKET", "aws-im-prod-aiworkflow")
S3_REGION = os.getenv("S3_REGION", "eu-central-1")


class S3Storage:
    """Async S3 client for binary file storage (images, recordings, binary artifacts)."""

    def __init__(self):
        self.bucket = S3_BUCKET
        self.region = S3_REGION
        self._session = aiobotocore.session.get_session()

    @asynccontextmanager
    async def _client(self):
        async with self._session.create_client(
            "s3",
            region_name=self.region,
            aws_access_key_id=os.getenv("S3_ACCESS_KEY_ID") or None,
            aws_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY") or None,
            endpoint_url=os.getenv("S3_ENDPOINT_URL") or None,
        ) as client:
            yield client

    async def upload(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Upload binary data to S3. Returns the key."""
        async with self._client() as client:
            await client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        logger.debug("S3 upload: %s (%d bytes)", key, len(data))
        return key

    async def download(self, key: str) -> bytes:
        """Download file from S3. Returns raw bytes."""
        async with self._client() as client:
            resp = await client.get_object(Bucket=self.bucket, Key=key)
            data = await resp["Body"].read()
        return data

    async def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Generate a presigned GET URL for temporary access."""
        async with self._client() as client:
            url = await client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        return url

    async def delete(self, key: str) -> None:
        """Delete a file from S3."""
        async with self._client() as client:
            await client.delete_object(Bucket=self.bucket, Key=key)
        logger.debug("S3 delete: %s", key)

    async def exists(self, key: str) -> bool:
        """Check if a key exists in S3. Only returns False for 404, re-raises other errors."""
        from botocore.exceptions import ClientError
        try:
            async with self._client() as client:
                await client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as e:
            if e.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                return False
            raise
        except Exception:
            raise


# Singleton instance
s3 = S3Storage()
