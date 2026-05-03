resource "aws_timestreamwrite_database" "main" {
  database_name = "${var.project_name}-${var.environment}"
}

resource "aws_timestreamwrite_table" "sensor_aggregates" {
  database_name = aws_timestreamwrite_database.main.database_name
  table_name    = "sensor_aggregates"

  retention_properties {
    memory_store_retention_period_in_hours  = var.memory_store_hours
    magnetic_store_retention_period_in_days = var.magnetic_store_days
  }

  magnetic_store_write_properties {
    enable_magnetic_store_writes = true
  }
}

resource "aws_timestreamwrite_table" "air_quality_alerts" {
  database_name = aws_timestreamwrite_database.main.database_name
  table_name    = "air_quality_alerts"

  retention_properties {
    memory_store_retention_period_in_hours  = var.memory_store_hours
    magnetic_store_retention_period_in_days = var.magnetic_store_days
  }

  magnetic_store_write_properties {
    enable_magnetic_store_writes = true
  }
}