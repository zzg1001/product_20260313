-- ============================================
-- AI Skills Platform - 数据库表结构
-- 数据库: MySQL 8.0+
-- 字符集: utf8mb4
-- ============================================

-- 删除旧表（按依赖顺序）
DROP TABLE IF EXISTS `workflow_executions`;
DROP TABLE IF EXISTS `workflows`;
DROP TABLE IF EXISTS `skills`;

-- ============================================
-- 1. 技能表 (skills)
-- 基本信息存数据库，脚本文件存文件系统
-- ============================================
CREATE TABLE `skills` (
    `id` VARCHAR(36) NOT NULL COMMENT '技能ID (UUID)',
    `name` VARCHAR(100) NOT NULL COMMENT '技能名称',
    `description` TEXT COMMENT '技能描述',
    `icon` VARCHAR(50) DEFAULT '⚡' COMMENT '图标（emoji或图标名）',
    `tags` JSON COMMENT '标签列表，如 ["Expert", "Public"]',
    `folder_path` VARCHAR(255) COMMENT '技能文件夹相对路径',
    `entry_script` VARCHAR(100) DEFAULT 'main.py' COMMENT '入口脚本文件名',
    `author` VARCHAR(50) COMMENT '作者',
    `version` VARCHAR(20) DEFAULT '1.0.0' COMMENT '版本号',
    `interactions` JSON COMMENT '交互配置列表',
    `output_config` JSON COMMENT '输出文件配置: {enabled: bool, preferred_type: string, filename_template: string}',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    INDEX `idx_skills_name` (`name`),
    INDEX `idx_skills_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='技能表';


-- ============================================
-- 2. 工作流表 (workflows)
-- ============================================
CREATE TABLE `workflows` (
    `id` VARCHAR(50) NOT NULL COMMENT '工作流ID（如 wf-xxx）',
    `name` VARCHAR(100) NOT NULL COMMENT '工作流名称',
    `description` TEXT COMMENT '工作流描述',
    `icon` VARCHAR(50) DEFAULT '🔄' COMMENT '图标',
    `nodes` JSON COMMENT '节点列表',
    `edges` JSON COMMENT '边列表',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    INDEX `idx_workflows_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='工作流表';


-- ============================================
-- 3. 工作流执行实例表 (workflow_executions)
-- ============================================
CREATE TABLE `workflow_executions` (
    `id` VARCHAR(50) NOT NULL COMMENT '执行ID (exec-xxx)',
    `workflow_id` VARCHAR(50) NOT NULL COMMENT '工作流ID',
    `workflow_name` VARCHAR(100) COMMENT '工作流名称快照',
    `status` ENUM('pending', 'running', 'paused', 'completed', 'failed') DEFAULT 'pending' COMMENT '执行状态',
    `current_step` INT DEFAULT 0 COMMENT '当前步骤',
    `total_steps` INT DEFAULT 0 COMMENT '总步骤数',
    `completed_steps` JSON COMMENT '已完成步骤列表',
    `pending_interaction` JSON COMMENT '等待的交互信息',
    `pre_inputs` JSON COMMENT '预收集的输入',
    `error` TEXT COMMENT '错误信息',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    PRIMARY KEY (`id`),
    INDEX `idx_executions_workflow_id` (`workflow_id`),
    INDEX `idx_executions_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='工作流执行实例表';
