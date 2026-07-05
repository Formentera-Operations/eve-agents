import {
  GetObjectCommand,
  HeadObjectCommand,
  PutObjectCommand,
  S3Client,
} from "@aws-sdk/client-s3";

export const CORPUS_BUCKET = "formentera-welldrive";
export const DERIVED_BUCKET = "formentera-welldrive-derived";
export const PARSE_CACHE_PREFIX = "runs/doc-intel/parsed/";

const client = new S3Client({
  region: process.env.AWS_REGION ?? "us-east-1",
});

export async function headMetadata(bucket: string, key: string) {
  const res = await client.send(
    new HeadObjectCommand({ Bucket: bucket, Key: key }),
  );
  return {
    metadata: res.Metadata ?? {},
    contentType: res.ContentType ?? "",
    bytes: res.ContentLength ?? 0,
    lastModified: res.LastModified?.toISOString() ?? "",
  };
}

export async function getObjectText(bucket: string, key: string): Promise<string> {
  const res = await client.send(
    new GetObjectCommand({ Bucket: bucket, Key: key }),
  );
  return (await res.Body?.transformToString()) ?? "";
}

export async function getObjectBytes(bucket: string, key: string): Promise<Uint8Array> {
  const res = await client.send(
    new GetObjectCommand({ Bucket: bucket, Key: key }),
  );
  return (await res.Body?.transformToByteArray()) ?? new Uint8Array();
}

export async function putObjectJson(bucket: string, key: string, value: unknown) {
  await client.send(
    new PutObjectCommand({
      Bucket: bucket,
      Key: key,
      Body: JSON.stringify(value),
      ContentType: "application/json",
    }),
  );
}

/** Parse an s3://bucket/key URI. */
export function parseS3Uri(uri: string): { bucket: string; key: string } | undefined {
  const m = uri.match(/^s3:\/\/([^/]+)\/(.+)$/);
  if (!m) return undefined;
  return { bucket: m[1], key: m[2] };
}
