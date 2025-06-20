from pyspark.sql import SparkSession
from pyspark.sql.functions import *
from pyspark.sql.types import *
from datetime import datetime
import boto3
import re
import sys

# Start Spark Session
spark = SparkSession.builder \
    .appName("ReadDataFromS3") \
    .config("spark.hadoop.fs.s3a.aws.credentials.provider", "com.amazonaws.auth.DefaultAWSCredentialsProviderChain") \
    .config("spark.hadoop.fs.s3a.impl", "org.apache.hadoop.fs.s3a.S3AFileSystem") \
    .config("spark.jars.packages", "org.apache.hadoop:hadoop-aws:3.3.1") \
    .getOrCreate()

# Define schema
schema = StructType([
    StructField("currency", StringType(), True),
    StructField("customer", StructType([
        StructField("account_age_days", LongType(), True),
        StructField("country", StringType(), True),
        StructField("customer_id", LongType(), True),
        StructField("email", StringType(), True),
        StructField("is_premium", BooleanType(), True),
    ]), True),
    StructField("order_id", StringType(), True),
    StructField("payment_method", StringType(), True),
    StructField("products", ArrayType(
        StructType([
            StructField("category", StringType(), True),
            StructField("in_stock", BooleanType(), True),
            StructField("name", StringType(), True),
            StructField("price", DoubleType(), True),
            StructField("product_id", LongType(), True),
            StructField("vendor", StringType(), True),
        ])
    ), True),
    StructField("shipping_cost", DoubleType(), True),
    StructField("shipping_method", StringType(), True),
    StructField("status", StringType(), True),
    StructField("subtotal", DoubleType(), True),
    StructField("tax", DoubleType(), True),
    StructField("timestamp", StringType(), True),
    StructField("total_amount", DoubleType(), True),
])

# State S3 input path and output details
bucket = "confluent-kafka-ecommerce-data"
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
input_prefix = "kafka-consumer-logs"
input_path = f"s3a://{bucket}/{input_prefix}/*.json"
output_path = "kafka-consumer-logs-output"
output_prefix = f"{output_path}/output_tmp_{timestamp}/"
tmp_dir = f"s3a://{bucket}/{output_path}/output_tmp_{timestamp}/"
final_key = f"{output_path}/output_{timestamp}.csv"

# Read data
df = spark.read.schema(schema).json(input_path)

# Flatten customer struct and explode products array into wider table
df_flat = df.withColumn("product", explode("products")) \
    .select(
        "*",
        col("customer.account_age_days"),
        col("customer.country"),
        col("customer.customer_id"),
        col("customer.email"),
        col("customer.is_premium"),
        col("product.*")
    ) \
    .drop("customer", "products", "product")

# Write to single CSV file in S3 
df_flat.coalesce(1).write.option("header", True).mode("overwrite").csv(tmp_dir)

# Rename the output file to a final name
s3 = boto3.client("s3")
response = s3.list_objects_v2(Bucket=bucket, Prefix=output_prefix)
for obj in response.get("Contents", []):
    key = obj["Key"]
    if re.match(rf"{output_prefix}part-.*\.csv", key):
        s3.copy_object(
            Bucket=bucket,
            CopySource={"Bucket": bucket, "Key": key},
            Key=final_key
        )
        s3.delete_object(Bucket=bucket, Key=key)

# Clean up and remove all temp files in the temp directory
response = s3.list_objects_v2(Bucket=bucket, Prefix=f"{output_path}/output_tmp_{timestamp}/")
for obj in response.get("Contents", []):
    s3.delete_object(Bucket=bucket, Key=obj["Key"])

# Print final output path
print("Data Converted from JSON to CSV and written to S3.")
print(f"Data written to: s3://{output_path}/{output_prefix}")

# Stop Spark session
spark.stop()