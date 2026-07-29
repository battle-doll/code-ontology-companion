from dataclasses import dataclass


@dataclass
class Order:
    identifier: str


def extract_orders(source):
    return source.read()


def transform_orders(records):
    return [record.strip() for record in records]


def load_orders(target, records):
    target.write(records)


def run_pipeline(source, target):
    records = extract_orders(source)
    cleaned = transform_orders(records)
    load_orders(target, cleaned)
