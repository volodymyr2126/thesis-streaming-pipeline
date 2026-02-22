 output "vpc_id" {
       value = module.network.vpc_id
     }

     output "public_subnet_ids" {
       value = module.network.public_subnet_ids
     }

     output "private_subnet_ids" {
       value = module.network.private_subnet_ids
     }

     output "data_lake_bucket_name" {
       value = module.storage.data_lake_bucket_name
     }

     output "log_group_name" {
       value = module.monitoring.log_group_name
     }

     output "sns_topic_arn" {
       value = module.monitoring.sns_topic_arn
     }