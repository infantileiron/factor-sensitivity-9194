<script setup lang="ts">
import {ref,computed,watch} from 'vue';
import {models} from '../stores/models';
import {spaces} from '../stores/spaces';
import {useMigration,type MigrationPreview} from '../stores/unitMigrations';
import {canWrite} from '../stores/auth';
import {useTask} from '../hooks/useTask';
import Notice from './common/Notice.vue';
import type {MigrationBody,FactorConversion} from '../api/unitMigrations';

const props=defineProps<{modelId:string}>();
const emit=defineEmits<{migrated:[]}>();
const {items:modelItems}=models;
const {items:spaceItems}=spaces;
const {preview,busy,error,runPreview,confirm,reset}=useMigration();
const {act}=useTask();
const spaceId=ref('');
const newModelName=ref('');
const newSpaceName=ref('');
const description=ref('按 x_new = scale × x_old + offset 迁移物理单位，旧底稿保持原值。');

const sourceModel=computed(()=>modelItems.value.find(m=>m.id===props.modelId));
const matchingSpaces=computed(()=>spaceItems.value.filter(s=>s.model_id===props.modelId));
watch(()=>props.modelId,()=>{reset();spaceId.value=matchingSpaces.value[0]?.id||''},{immediate:true});

interface Row extends FactorConversion{enabled:boolean}
const rows=ref<Row[]>([]);
watch(sourceModel,(m)=>{
 rows.value=(m?.factors||[]).map((f:any)=>({
  factor_id:f.factor_id,scale:1,offset:0,new_unit:f.unit,enabled:false,
 }));
 reset();
},{immediate:true});

function buildBody():MigrationBody{
 return {
  source_model_id:props.modelId,
  source_space_id:spaceId.value,
  new_model_name:newModelName.value,
  new_space_name:newSpaceName.value,
  description:description.value,
  conversions:rows.value.filter(r=>r.enabled).map(({factor_id,scale,offset,new_unit})=>({factor_id,scale,offset,new_unit})),
 };
}
function doPreview(){act(()=>runPreview(buildBody()))}
async function doConfirm(){
 await act(async()=>{
  await confirm(buildBody());
  await Promise.all([models.load(),spaces.load()]);
  newModelName.value='';newSpaceName.value='';
  rows.value.forEach(r=>{r.enabled=false;r.scale=1;r.offset=0});
  emit('migrated');
 });
}
const ledger=computed(()=>(preview.value as MigrationPreview|null)?.comparison);
</script>

<template>
 <section class="migration-panel editor-panel">
  <p class="eyebrow">AFFINE UNIT MIGRATION</p>
  <h2>单位迁移 · 正比例缩放与平移</h2>
  <p class="method-note">
   对勾选因子应用 <b>x_new = scale × x_old + offset</b>，自动换算截距、线性项、二次项、两两交互项与物理范围；
   同一工况的响应与 Morris/Sobol 敏感度保持一致。迁移只建立新版模型与因子空间，旧研究、运行与归档底稿保持原值。
  </p>
  <label>源因子空间（物理范围随迁）
   <select v-model="spaceId">
    <option v-for="s in matchingSpaces" :key="s.id" :value="s.id">{{s.name}}</option>
   </select>
  </label>
  <div class="table-wrap">
   <table>
    <thead><tr><th>迁移</th><th>因子</th><th>原单位</th><th>scale 正比例</th><th>offset 平移</th><th>新单位</th></tr></thead>
    <tbody>
     <tr v-for="r in rows" :key="r.factor_id">
      <td><input class="check" type="checkbox" v-model="r.enabled"></td>
      <td><b>{{r.factor_id}}</b></td>
      <td>{{sourceModel?.factors.find((f:any)=>f.factor_id===r.factor_id)?.unit}}</td>
      <td><input type="number" step="any" min="0" v-model.number="r.scale" :disabled="!r.enabled"></td>
      <td><input type="number" step="any" v-model.number="r.offset" :disabled="!r.enabled"></td>
      <td><input v-model="r.new_unit" :disabled="!r.enabled"></td>
     </tr>
    </tbody>
   </table>
  </div>
  <div class="form-pair">
   <label>新版模型名称<input v-model="newModelName" minlength="2" placeholder="如：XH-C06 公制单位版"></label>
   <label>新版空间名称<input v-model="newSpaceName" minlength="2" placeholder="如：XH-C06 公制单位范围"></label>
  </div>
  <label>迁移说明<input v-model="description"></label>
  <Notice :message="error"/>
  <div class="actions">
   <button type="button" class="secondary" :disabled="busy||!rows.some(r=>r.enabled)||!newModelName||!newSpaceName" @click="doPreview">试算并核对新旧输入</button>
  </div>

  <template v-if="preview && ledger">
   <div class="ledger-head">
    <h3>换算核对（尚未保存）</h3>
    <p class="warning-notes" v-if="preview.name_conflict" style="margin:0">新版模型或空间名称已存在，请改名后再确认。</p>
   </div>
   <p class="method-note">公式：{{ledger.formula}}；截距 {{ledger.intercept.old}} → {{ledger.intercept.new}} kWh</p>
   <div class="table-wrap">
    <table>
     <thead>
      <tr><th>因子</th><th>单位 旧→新</th><th>线性 旧→新</th><th>二次 旧→新</th><th>范围下界 旧→新</th><th>范围上界 旧→新</th></tr>
     </thead>
     <tbody>
      <tr v-for="f in ledger.factors" :key="f.factor_id" :class="{muted:!f.changed}">
       <td><b>{{f.factor_id}}</b><small>s={{f.scale}} o={{f.offset}}</small></td>
       <td>{{f.old_unit}} → {{f.new_unit}}</td>
       <td>{{f.old_linear}} → {{f.new_linear}}</td>
       <td>{{f.old_quadratic}} → {{f.new_quadratic}}</td>
       <td>{{f.old_low}} → {{f.new_low}}</td>
       <td>{{f.old_high}} → {{f.new_high}}</td>
      </tr>
     </tbody>
    </table>
   </div>
   <p class="interaction-note" v-if="ledger.interactions.length">
    交互项核对：
    <span v-for="(p,i) in ledger.interactions" :key="i">{{p.left}}×{{p.right}}：{{p.old_coefficient}} → {{p.new_coefficient}}　</span>
   </p>
   <button type="button" v-if="canWrite()" :disabled="busy||preview.name_conflict||!newModelName||!newSpaceName" @click="doConfirm">确认迁移并建立新版模型与因子空间</button>
  </template>
 </section>
</template>
