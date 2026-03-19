<script setup lang="ts">
import { ref, onMounted } from 'vue'

const currentTab = ref('智能制造')
const tabs = ['智能制造', '数字医疗', '新零售', '能源电力']

function selectTab(tab: string) {
  currentTab.value = tab
}

onMounted(() => {
  // Header scroll effect
  const header = document.querySelector('.header') as HTMLElement
  if (header) {
    window.addEventListener('scroll', () => {
      if (window.scrollY > 50) {
        header.style.boxShadow = '0 2px 10px rgba(0,0,0,0.1)'
      } else {
        header.style.boxShadow = 'none'
      }
    })
  }
})

function scrollTo(id: string) {
  const target = document.querySelector(id)
  if (target) {
    const headerHeight = 64
    const targetPosition = target.getBoundingClientRect().top + window.pageYOffset - headerHeight
    window.scrollTo({
      top: targetPosition,
      behavior: 'smooth'
    })
  }
}
</script>

<template>
  <div class="home-page">
    <!-- Header -->
    <header class="header">
      <div class="container">
        <div class="header-inner">
          <a href="/" class="logo">
            <div class="logo-icon">IK</div>
            <div class="logo-text">Ike Data<span>工业智能</span></div>
          </a>

          <nav class="nav">
            <ul class="nav-links">
              <li><a href="#products" @click.prevent="scrollTo('#products')" class="active">产品</a></li>
              <li><a href="#solutions" @click.prevent="scrollTo('#solutions')">解决方案</a></li>
              <li><a href="#customers" @click.prevent="scrollTo('#customers')">客户案例</a></li>
              <li><a href="#projects" @click.prevent="scrollTo('#projects')">快速入口</a></li>
              <li><a href="#contact" @click.prevent="scrollTo('#contact')">关于我们</a></li>
            </ul>
          </nav>

          <div class="header-actions">
            <button class="btn btn-text">登录</button>
            <button class="btn btn-primary" @click="scrollTo('#projects')">免费试用</button>
          </div>
        </div>
      </div>
    </header>

    <!-- Hero Section -->
    <section class="hero">
      <div class="container">
        <div class="hero-inner">
          <div class="hero-content">
            <div class="hero-badge">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
              </svg>
              工业 4.0 智能解决方案
            </div>

            <h1 class="hero-title">
              用 AI 赋能<span class="highlight">智能制造</span><br>
              驱动产业数字化升级
            </h1>

            <p class="hero-desc">
              宜氪数据提供基于 AI 大模型的一站式工业智能解决方案，
              覆盖数据采集、智能分析、预测维护等全流程，
              助力制造企业实现降本增效。
            </p>

            <div class="hero-buttons">
              <a href="#products" @click.prevent="scrollTo('#products')" class="btn btn-primary btn-lg btn-icon">
                <span>了解产品</span>
                <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 8l4 4m0 0l-4 4m4-4H3"/>
                </svg>
              </a>
              <a href="#contact" @click.prevent="scrollTo('#contact')" class="btn btn-outline btn-lg">联系我们</a>
            </div>

            <div class="hero-stats">
              <div class="hero-stat">
                <div class="hero-stat-value">500<span>+</span></div>
                <div class="hero-stat-label">服务企业</div>
              </div>
              <div class="hero-stat">
                <div class="hero-stat-value">50<span>+</span></div>
                <div class="hero-stat-label">世界500强客户</div>
              </div>
              <div class="hero-stat">
                <div class="hero-stat-value">30<span>%</span></div>
                <div class="hero-stat-label">平均效率提升</div>
              </div>
            </div>
          </div>

          <div class="hero-visual">
            <div class="hero-image">
              <div class="hero-dashboard">
                <div class="dashboard-header">
                  <div class="dashboard-dot red"></div>
                  <div class="dashboard-dot yellow"></div>
                  <div class="dashboard-dot green"></div>
                  <span class="dashboard-title">生产监控大屏</span>
                </div>
                <div class="dashboard-grid">
                  <div class="dashboard-card">
                    <div class="dashboard-card-label">设备运行率</div>
                    <div class="dashboard-card-value up">96.8%</div>
                  </div>
                  <div class="dashboard-card">
                    <div class="dashboard-card-label">产能利用</div>
                    <div class="dashboard-card-value">87.2%</div>
                  </div>
                  <div class="dashboard-card">
                    <div class="dashboard-card-label">预警数量</div>
                    <div class="dashboard-card-value accent">3</div>
                  </div>
                  <div class="dashboard-chart">
                    <div class="chart-bar" style="height: 60%"></div>
                    <div class="chart-bar" style="height: 80%"></div>
                    <div class="chart-bar" style="height: 45%"></div>
                    <div class="chart-bar" style="height: 90%"></div>
                    <div class="chart-bar" style="height: 70%"></div>
                    <div class="chart-bar" style="height: 85%"></div>
                    <div class="chart-bar" style="height: 55%"></div>
                    <div class="chart-bar" style="height: 95%"></div>
                  </div>
                </div>
              </div>

              <div class="floating-card card-1">
                <div class="floating-icon blue">
                  <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                  </svg>
                </div>
                <div class="floating-text">
                  <strong>实时监控</strong>
                  <span class="status-ok">设备状态正常</span>
                </div>
              </div>

              <div class="floating-card card-2">
                <div class="floating-icon orange">
                  <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/>
                  </svg>
                </div>
                <div class="floating-text">
                  <strong>AI 预测</strong>
                  <span>效率提升 28%</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Products Section -->
    <section id="products" class="products">
      <div class="container">
        <div class="section-header">
          <div class="section-tag">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/>
            </svg>
            产品服务
          </div>
          <h2 class="section-title">全栈 AI 产品矩阵</h2>
          <p class="section-desc">基于大模型和行业知识，构建面向工业场景的智能产品生态</p>
        </div>

        <div class="products-grid">
          <div class="product-card">
            <div class="product-icon blue">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
              </svg>
            </div>
            <h3>AI Agent</h3>
            <p>智能对话代理，支持多轮交互、任务规划，实现业务流程自动化</p>
            <div class="arrow">了解更多 <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 8l4 4m0 0l-4 4m4-4H3"/></svg></div>
          </div>

          <router-link to="/skills" class="product-card clickable">
            <div class="product-icon purple">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"/>
              </svg>
            </div>
            <h3>AI Skills</h3>
            <p>可复用技能库，支持技能编排、一键部署，快速构建业务能力</p>
            <div class="arrow">了解更多 <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 8l4 4m0 0l-4 4m4-4H3"/></svg></div>
          </router-link>

          <div class="product-card">
            <div class="product-icon cyan">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
              </svg>
            </div>
            <h3>模型管理</h3>
            <p>统一模型配置中心，多模型切换、版本管理、性能监控</p>
            <div class="arrow">了解更多 <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 8l4 4m0 0l-4 4m4-4H3"/></svg></div>
          </div>

          <div class="product-card">
            <div class="product-icon orange">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"/>
              </svg>
            </div>
            <h3>工业数据平台</h3>
            <p>支持海量工业数据接入、存储、治理和分析一站式服务</p>
            <div class="arrow">了解更多 <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 8l4 4m0 0l-4 4m4-4H3"/></svg></div>
          </div>

          <div class="product-card">
            <div class="product-icon green">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>
              </svg>
            </div>
            <h3>智能数仓</h3>
            <p>智能数据仓库，支持数据建模、ETL、智能查询与报表</p>
            <div class="arrow">了解更多 <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 8l4 4m0 0l-4 4m4-4H3"/></svg></div>
          </div>

          <div class="product-card">
            <div class="product-icon magenta">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
              </svg>
            </div>
            <h3>任务调度</h3>
            <p>智能任务编排，支持定时任务、工作流管理与实时监控</p>
            <div class="arrow">了解更多 <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 8l4 4m0 0l-4 4m4-4H3"/></svg></div>
          </div>

          <div class="product-card">
            <div class="product-icon red">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/>
              </svg>
            </div>
            <h3>预测维护</h3>
            <p>基于AI的设备健康预测，提前预警故障，降低停机损失</p>
            <div class="arrow">了解更多 <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 8l4 4m0 0l-4 4m4-4H3"/></svg></div>
          </div>

          <div class="product-card">
            <div class="product-icon geek">
              <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4"/>
              </svg>
            </div>
            <h3>智能配置</h3>
            <p>动态配置管理，支持灰度发布、版本回滚与配置中心</p>
            <div class="arrow">了解更多 <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 8l4 4m0 0l-4 4m4-4H3"/></svg></div>
          </div>
        </div>
      </div>
    </section>

    <!-- Solutions Section -->
    <section id="solutions" class="solutions">
      <div class="container">
        <div class="section-header">
          <div class="section-tag">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"/>
            </svg>
            解决方案
          </div>
          <h2 class="section-title">行业智能化解决方案</h2>
          <p class="section-desc">深耕多个行业领域，提供端到端的智能化转型方案</p>
        </div>

        <div class="solutions-tabs">
          <button
            v-for="tab in tabs"
            :key="tab"
            class="solution-tab"
            :class="{ active: currentTab === tab }"
            @click="selectTab(tab)"
          >{{ tab }}</button>
        </div>

        <div class="solution-content">
          <div class="solution-info">
            <h3>{{ currentTab }}解决方案</h3>
            <p>
              通过 AI 技术与工业物联网深度融合，打造智能工厂，实现生产过程的数字化、
              网络化、智能化，帮助制造企业提升生产效率、降低运营成本、优化产品质量。
            </p>

            <div class="solution-features">
              <div class="solution-feature">
                <div class="solution-feature-icon">
                  <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
                </div>
                <span>设备实时监控与预警</span>
              </div>
              <div class="solution-feature">
                <div class="solution-feature-icon">
                  <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
                </div>
                <span>生产排程智能优化</span>
              </div>
              <div class="solution-feature">
                <div class="solution-feature-icon">
                  <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
                </div>
                <span>质量追溯与分析</span>
              </div>
              <div class="solution-feature">
                <div class="solution-feature-icon">
                  <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
                </div>
                <span>能耗管理与优化</span>
              </div>
            </div>

            <a href="#" class="btn btn-primary btn-icon">
              查看详情
              <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 8l4 4m0 0l-4 4m4-4H3"/></svg>
            </a>
          </div>

          <div class="solution-visual">
            <div class="solution-diagram">
              <div class="diagram-node">
                <div class="diagram-node-icon">
                  <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"/></svg>
                </div>
                <span>设备层</span>
              </div>
              <div class="diagram-node">
                <div class="diagram-node-icon">
                  <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7"/></svg>
                </div>
                <span>数据层</span>
              </div>
              <div class="diagram-node">
                <div class="diagram-node-icon">
                  <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2z"/></svg>
                </div>
                <span>分析层</span>
              </div>
              <div class="diagram-node diagram-center">
                <div class="diagram-node-icon">
                  <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                </div>
                <span>AI 智能决策引擎</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Customers Section -->
    <section id="customers" class="customers">
      <div class="container">
        <div class="section-header">
          <div class="section-tag">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"/>
            </svg>
            客户案例
          </div>
          <h2 class="section-title">深受全球领先企业信赖</h2>
          <p class="section-desc">与众多世界500强企业建立深度合作关系</p>
        </div>

        <div class="customers-logos">
          <span class="customer-logo">ExxonMobil</span>
          <span class="customer-logo">Saint-Gobain</span>
          <span class="customer-logo">LVMH</span>
          <span class="customer-logo">中国烟草</span>
          <span class="customer-logo">华为</span>
          <span class="customer-logo">微软</span>
        </div>

        <div class="testimonial">
          <p class="testimonial-quote">
            宜氪数据的智能制造解决方案帮助我们实现了生产线的全面数字化升级，
            设备利用率提升了35%，故障预警准确率达到95%以上，显著降低了运维成本。
          </p>
          <div class="testimonial-author">
            <div class="testimonial-avatar">张</div>
            <div class="testimonial-info">
              <div class="testimonial-name">张总监</div>
              <div class="testimonial-role">某世界500强制造企业 · 数字化负责人</div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Projects Section -->
    <section id="projects" class="projects">
      <div class="container">
        <div class="section-header">
          <div class="section-tag">
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/>
            </svg>
            快速入口
          </div>
          <h2 class="section-title">平台与服务入口</h2>
          <p class="section-desc">一站式访问宜氪数据的各类平台与服务</p>
        </div>

        <div class="projects-grid">
          <router-link to="/skills" class="project-card">
            <div class="project-card-header">
              <div class="project-card-icon blue">
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
              </div>
              <h3>AI Skills 平台</h3>
            </div>
            <p>技能管理与执行中心，快速构建和部署 AI 能力</p>
            <div class="project-card-footer">
              <span class="project-card-tag">核心平台</span>
              <div class="project-card-arrow">
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 8l4 4m0 0l-4 4m4-4H3"/></svg>
              </div>
            </div>
          </router-link>

          <a href="http://localhost:5174" target="_blank" class="project-card">
            <div class="project-card-header">
              <div class="project-card-icon purple">
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
                </svg>
              </div>
              <h3>后台管理系统</h3>
            </div>
            <p>系统配置与管理中心，模型、权限、日志一站式管理</p>
            <div class="project-card-footer">
              <span class="project-card-tag">管理后台</span>
              <div class="project-card-arrow">
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 8l4 4m0 0l-4 4m4-4H3"/></svg>
              </div>
            </div>
          </a>

          <div class="project-card" style="cursor: pointer;" @click="alert('请扫描公众号二维码关注我们')">
            <div class="project-card-header">
              <div class="project-card-icon green">
                <svg fill="currentColor" viewBox="0 0 24 24"><path d="M8.691 2.188C3.891 2.188 0 5.476 0 9.53c0 2.212 1.17 4.203 3.002 5.55a.59.59 0 01.213.665l-.39 1.48c-.019.07-.048.141-.048.213 0 .163.13.295.29.295a.326.326 0 00.167-.054l1.903-1.114a.864.864 0 01.717-.098 10.16 10.16 0 002.837.403c.276 0 .543-.027.811-.05-.857-2.578.157-4.972 1.932-6.446 1.703-1.415 3.882-1.98 5.853-1.838-.576-3.583-4.196-6.348-8.596-6.348z"/></svg>
              </div>
              <h3>公众号</h3>
            </div>
            <p>关注获取最新动态、行业洞察与技术分享</p>
            <div class="project-card-footer">
              <span class="project-card-tag">资讯动态</span>
              <div class="project-card-arrow">
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 8l4 4m0 0l-4 4m4-4H3"/></svg>
              </div>
            </div>
          </div>

          <a href="#" class="project-card">
            <div class="project-card-header">
              <div class="project-card-icon orange">
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"/></svg>
              </div>
              <h3>OA 系统</h3>
            </div>
            <p>企业办公协同平台，流程审批与内部协作</p>
            <div class="project-card-footer">
              <span class="project-card-tag">内部系统</span>
              <div class="project-card-arrow">
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 8l4 4m0 0l-4 4m4-4H3"/></svg>
              </div>
            </div>
          </a>
        </div>
      </div>
    </section>

    <!-- CTA Section -->
    <section id="contact" class="cta">
      <div class="container">
        <div class="cta-content">
          <h2>开启您的智能化转型之旅</h2>
          <p>联系我们，获取专属解决方案咨询与产品演示</p>
          <div class="cta-buttons">
            <a href="mailto:contact@ikedata.com" class="btn btn-white btn-lg btn-icon">
              免费咨询
              <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 8l4 4m0 0l-4 4m4-4H3"/></svg>
            </a>
            <a href="tel:021-12345678" class="btn btn-ghost btn-lg">021-12345678</a>
          </div>
        </div>
      </div>
    </section>

    <!-- Footer -->
    <footer class="footer">
      <div class="container">
        <div class="footer-grid">
          <div class="footer-brand">
            <a href="/" class="logo">
              <div class="logo-icon">IK</div>
              <div class="logo-text">Ike Data</div>
            </a>
            <p>上海宜氪数据科技有限公司<br>专注于工业智能制造领域的 AI 解决方案提供商</p>
          </div>
          <div class="footer-col">
            <h4>产品</h4>
            <ul>
              <li><a href="#products" @click.prevent="scrollTo('#products')">AI Agent</a></li>
              <li><router-link to="/skills">AI Skills</router-link></li>
              <li><a href="#products" @click.prevent="scrollTo('#products')">模型管理</a></li>
              <li><a href="#products" @click.prevent="scrollTo('#products')">工业数据平台</a></li>
            </ul>
          </div>
          <div class="footer-col">
            <h4>解决方案</h4>
            <ul>
              <li><a href="#solutions" @click.prevent="scrollTo('#solutions')">智能制造</a></li>
              <li><a href="#solutions" @click.prevent="scrollTo('#solutions')">数字医疗</a></li>
              <li><a href="#solutions" @click.prevent="scrollTo('#solutions')">新零售</a></li>
              <li><a href="#solutions" @click.prevent="scrollTo('#solutions')">能源电力</a></li>
            </ul>
          </div>
          <div class="footer-col">
            <h4>资源</h4>
            <ul>
              <li><a href="#">文档中心</a></li>
              <li><a href="#">API 参考</a></li>
              <li><a href="#">最佳实践</a></li>
              <li><a href="#">开发者社区</a></li>
            </ul>
          </div>
          <div class="footer-col">
            <h4>联系我们</h4>
            <ul>
              <li><a href="#">上海市</a></li>
              <li><a href="mailto:contact@ikedata.com">contact@ikedata.com</a></li>
              <li><a href="tel:021-12345678">021-12345678</a></li>
            </ul>
          </div>
        </div>
        <div class="footer-bottom">
          <p>&copy; 2018-2026 上海宜氪数据科技有限公司. All rights reserved.</p>
          <div class="footer-links">
            <a href="#">隐私政策</a>
            <a href="#">服务条款</a>
            <a href="#">沪ICP备xxxxxxxx号</a>
          </div>
        </div>
      </div>
    </footer>
  </div>
</template>

<style>
@import './HomePage.css';
</style>
