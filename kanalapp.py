import streamlit as st
import re
import pandas as pd
from datetime import datetime
import io
import zipfile

# --- 웹 페이지 기본 설정 ---
st.set_page_config(page_title="카카오톡 단톡방 분석기", layout="wide", page_icon="📊")
st.title("📊 카카오톡 단톡방 인원 및 활동 분석기")

# [최적화 1] 정규표현식 글로벌 컴파일 (매번 생성되는 오버헤드 제거)
DATE_PATTERN_1 = re.compile(r"^-+ (\d{4})년 (\d{1,2})월 (\d{1,2})일 .*-+$") 
DATE_PATTERN_2 = re.compile(r"^(\d{4})년 (\d{1,2})월 (\d{1,2})일 [월화수목금토일]요일$") 
CHAT_PC = re.compile(r"^\[(.*?)\] \[(오전|오후) (\d{1,2}):(\d{1,2})\] (.*)$")
CHAT_IOS = re.compile(r"^(\d{4})\. ?(\d{1,2})\. ?(\d{1,2})\. (?:(오전|오후) )?(\d{1,2}):(\d{1,2}), (.*?) : (.*)$")
CHAT_AND = re.compile(r"^(\d{4})년 (\d{1,2})월 (\d{1,2})일 (오전|오후) (\d{1,2}):(\d{1,2}), (.*?) : (.*)$")
HIDDEN_MSG_TEXT = "관리자가 메시지를 가렸습니다."
HIDDEN_MSG_IOS = re.compile(r"^(\d{4})\. ?(\d{1,2})\. ?(\d{1,2})\. (?:(오전|오후) )?(\d{1,2}):(\d{1,2}): (관리자가 메시지를 가렸습니다\.)$")
SYS_ACTION_PATTERN = r"(들어왔습니다\.|나갔습니다\.|내보냈습니다\.)"
SYS_PC = re.compile(rf"^(.*?)(님이|님을) {SYS_ACTION_PATTERN}")
SYS_IOS = re.compile(rf"^(\d{{4}})\. ?(\d{{1,2}})\. ?(\d{{1,2}})\. (?:(오전|오후) )?(\d{{1,2}}):(\d{{1,2}})[,:] (.*?)(님이|님을) {SYS_ACTION_PATTERN}")
SYS_AND = re.compile(rf"^(\d{{4}})년 (\d{{1,2}})월 (\d{{1,2}})일 (오전|오후) (\d{{1,2}}):(\d{{1,2}}), (.*?)(님이|님을) {SYS_ACTION_PATTERN}")
VALID_SYS_COMBOS = [("님이", "들어왔습니다."), ("님이", "나갔습니다."), ("님을", "내보냈습니다.")]

# --- 메시지 정규화 함수 ---
def normalize_msg(msg):
    msg = re.sub(r'\(?(이모티콘|Emoticons)\)?', '', msg)
    msg = re.sub(r'^이모티콘\s+', '', msg)
    msg = msg.replace("'일정 취소'", "'일정 삭제'").strip()
    return msg

# [최적화 2] Streamlit 캐싱 적용 (동일한 텍스트 파일은 재분석하지 않음)
@st.cache_data(show_spinner=False)
def parse_kakao_file(file_content):
    data = []
    current_date = None
    last_seen_minute_key = None
    ms_offset = 0  
    
    # splitlines()를 통한 빠른 이터레이션
    for line in file_content.splitlines():
        line_clean = line.strip()
        if not line_clean: continue
        
        match_date = DATE_PATTERN_1.match(line_clean) or DATE_PATTERN_2.match(line_clean)
        if match_date:
            y, m, d = match_date.groups()
            current_date = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
            last_seen_minute_key = None; ms_offset = 0
            continue
        
        m_hidden_ios = HIDDEN_MSG_IOS.match(line_clean)
        if m_hidden_ios or HIDDEN_MSG_TEXT in line_clean:
            if m_hidden_ios:
                y, m, d, ampm, h, mnt, _ = m_hidden_ios.groups()
                hour = int(h)
                if ampm == '오후' and hour != 12: hour += 12
                if ampm == '오전' and hour == 12: hour = 0
                minute_key = f"{current_date} {hour:02d}:{mnt.zfill(2)}"
            else: 
                minute_key = last_seen_minute_key if last_seen_minute_key else f"{current_date} 00:00"
            
            if minute_key == last_seen_minute_key: ms_offset += 1
            else: last_seen_minute_key = minute_key; ms_offset = 0
            
            time_str = f"{minute_key[-5:]}:00.{ms_offset:03d}"
            data.append({'Datetime_Str': f"{current_date} {time_str}", 'Date': current_date, 'Name': '시스템', 'Message': HIDDEN_MSG_TEXT, 'Type': 'Chat', 'Source': 'iPhone' if m_hidden_ios else 'PC'})
            continue

        m_pc = CHAT_PC.match(line_clean); m_ios = CHAT_IOS.match(line_clean); m_and = CHAT_AND.match(line_clean)
        time_info = None
        if m_pc: name, ampm, h, mnt, msg = m_pc.groups(); time_info = (ampm, h, mnt)
        elif m_ios: y, m, d, ampm, h, mnt, name, msg = m_ios.groups(); current_date = f"{y}-{m.zfill(2)}-{d.zfill(2)}"; time_info = (ampm, h, mnt)
        elif m_and: y, m, d, ampm, h, mnt, name, msg = m_and.groups(); current_date = f"{y}-{m.zfill(2)}-{d.zfill(2)}"; time_info = (ampm, h, mnt)

        if time_info and current_date:
            ampm, h, mnt = time_info; hour = int(h)
            if ampm == '오후' and hour != 12: hour += 12
            if ampm == '오전' and hour == 12: hour = 0
            minute_key = f"{current_date} {hour:02d}:{mnt.zfill(2)}"
            
            if minute_key == last_seen_minute_key: ms_offset += 1
            else: last_seen_minute_key = minute_key; ms_offset = 0
            
            time_str = f"{minute_key[-5:]}:00.{ms_offset:03d}"
            data.append({'Datetime_Str': f"{current_date} {time_str}", 'Date': current_date, 'Name': name, 'Message': msg, 'Type': 'Chat', 'Source': 'iPhone' if m_ios else ('Android' if m_and else 'PC')})
            continue

        m_sys_ios = SYS_IOS.match(line_clean); m_sys_and = SYS_AND.match(line_clean); m_sys_pc = SYS_PC.match(line_clean)
        if m_sys_ios or m_sys_and:
            y, m, d, ampm, h, mnt, name, josa, action = (m_sys_ios or m_sys_and).groups()
            if (josa, action) in VALID_SYS_COMBOS:
                current_date = f"{y}-{m.zfill(2)}-{d.zfill(2)}"; hour = int(h)
                if ampm == '오후' and hour != 12: hour += 12
                if ampm == '오전' and hour == 12: hour = 0
                minute_key = f"{current_date} {hour:02d}:{mnt.zfill(2)}"
                if minute_key == last_seen_minute_key: ms_offset += 1
                else: last_seen_minute_key = minute_key; ms_offset = 0
                time_str = f"{minute_key[-5:]}:00.{ms_offset:03d}"
                data.append({'Datetime_Str': f"{current_date} {time_str}", 'Date': current_date, 'Name': name, 'Message': f"{name}{josa} {action}", 'Type': 'System', 'Source': 'iPhone' if m_sys_ios else 'Android'})
            continue
        elif m_sys_pc:
            name, josa, action = m_sys_pc.groups()
            if (josa, action) in VALID_SYS_COMBOS and current_date and len(name) < 40: 
                minute_key = last_seen_minute_key if last_seen_minute_key else f"{current_date} 00:00"
                if minute_key == last_seen_minute_key: ms_offset += 1
                else: last_seen_minute_key = minute_key; ms_offset = 0
                time_str = f"{minute_key[-5:]}:00.{ms_offset:03d}"
                data.append({'Datetime_Str': f"{current_date} {time_str}", 'Date': current_date, 'Name': name, 'Message': f"{name}{josa} {action}", 'Type': 'System', 'Source': 'PC'})
            continue

        if data and data[-1]['Type'] == 'Chat':
            data[-1]['Message'] += '\n' + line.replace('\r', '').replace('\n', '')
            
    df = pd.DataFrame(data)
    if not df.empty:
        # 벡터화된 날짜 변환으로 속도 극대화
        df['Datetime'] = pd.to_datetime(df['Datetime_Str'])
        df.drop(columns=['Datetime_Str'], inplace=True)
    return df

# --- 웹 인터페이스 구성 ---
st.info("""
**카카오톡 텍스트(.txt) 또는 압축파일(.zip)을 업로드하세요.**
iOS/안드로이드/PC 버전의 대화 파일을 모두 지원하지만  
PC버전은 중간중간 대화가 끊겨있을 수 있기 때문에
**모바일 기기의 대화 백업**을 이용하시는 것을 추천드립니다.
""")

uploaded_files = st.file_uploader("파일 업로드", type=["txt", "zip"], accept_multiple_files=True, label_visibility="collapsed")

if uploaded_files:
    if st.button("분석 시작", type="primary"):
        with st.spinner("데이터 고속 분석 및 지능형 병합 중..."):
            df_list = []
            for uf in uploaded_files:
                if uf.name.lower().endswith('.zip'):
                    try:
                        with zipfile.ZipFile(uf) as z:
                            txt_files = [f for f in z.namelist() if f.lower().endswith('.txt')]
                            for t_file in txt_files:
                                with z.open(t_file) as f:
                                    content = f.read().decode('utf-8-sig')
                                    df_list.append(parse_kakao_file(content))
                    except Exception as e:
                        st.error(f"ZIP 읽기 에러: {uf.name} ({e})")
                elif uf.name.lower().endswith('.txt'):
                    content = uf.read().decode('utf-8-sig')
                    df_list.append(parse_kakao_file(content))
            
            df_combined = pd.concat([d for d in df_list if not d.empty], ignore_index=True)
            if df_combined.empty: 
                st.warning("분석할 유효한 데이터가 없습니다.")
                st.stop()

            # --- 중복 제거 및 병합 로직 ---
            source_priority = {'iPhone': 0, 'Android': 1, 'PC': 2}
            
            df_chat = df_combined[df_combined['Type'] == 'Chat'].copy()
            df_chat['Match_Msg'] = df_chat['Message'].apply(normalize_msg)
            df_chat['Minute_Key'] = df_chat['Datetime'].dt.strftime('%Y-%m-%d %H:%M')
            df_chat.loc[df_chat['Message'].str.contains('가렸습니다'), 'Minute_Key'] = 'HIDDEN_POOL'
            df_chat['Priority'] = df_chat['Source'].map(source_priority).fillna(9)
            df_chat = df_chat.sort_values(by=['Minute_Key', 'Name', 'Match_Msg', 'Source', 'Datetime'])
            df_chat['Seq'] = df_chat.groupby(['Minute_Key', 'Name', 'Match_Msg', 'Source']).cumcount()
            df_chat = df_chat.sort_values(by=['Minute_Key', 'Name', 'Match_Msg', 'Seq', 'Priority'])
            df_chat_cleaned = df_chat.drop_duplicates(subset=['Minute_Key', 'Name', 'Match_Msg', 'Seq'], keep='first')

            df_sys = df_combined[df_combined['Type'] == 'System'].copy()
            if not df_sys.empty:
                df_sys['Priority'] = df_sys['Source'].map(source_priority).fillna(9)
                df_sys_cleaned = df_sys.sort_values(by=['Date', 'Name', 'Message', 'Priority']).drop_duplicates(subset=['Date', 'Name', 'Message'], keep='first')
            else: df_sys_cleaned = df_sys

            df_final_master = pd.concat([df_chat_cleaned, df_sys_cleaned]).sort_values('Datetime').reset_index(drop=True)
            
            # --- 집계 로직 ---
            summary = df_chat_cleaned[df_chat_cleaned['Name'] != '시스템'].groupby('Name').agg(Last_Chat_Date=('Datetime', 'max'), Last_Message=('Message', 'last'), Count=('Message', 'count')).reset_index()
            
            def get_history(x):
                x = x.sort_values('Datetime')
                actions = []
                
                # [최적화 3] iterrows() 대신 itertuples() 사용 (압도적인 속도 향상)
                for row in x.itertuples():
                    msg = row.Message
                    date_str = row.Date
                    if "들어왔습니다" in msg: actions.append(f"[{date_str}] 입장")
                    elif "나갔습니다" in msg: actions.append(f"[{date_str}] 퇴장")
                    elif "내보냈습니다" in msg: actions.append(f"[{date_str}] 강퇴")
                
                last_sys_date = x.iloc[-1]['Datetime'] if not x.empty else pd.Timestamp.min
                
                if not actions:
                    return pd.Series({'First_Action': '-', 'Action_History': '-', 'Last_Action_Type': x.iloc[-1]['Message'], 'Last_Sys_Date': last_sys_date})
                
                if "입장" in actions[0]:
                    first = actions[0]
                    history_list = actions[1:]
                else:
                    first = '-'
                    history_list = actions[:]
                
                history = '\n'.join(history_list[::-1]) if history_list else '-'
                return pd.Series({'First_Action': first, 'Action_History': history, 'Last_Action_Type': x.iloc[-1]['Message'], 'Last_Sys_Date': last_sys_date})
            
            sys_sum = df_sys_cleaned.groupby('Name').apply(get_history, include_groups=False).reset_index() if not df_sys_cleaned.empty else pd.DataFrame(columns=['Name', 'First_Action', 'Action_History', 'Last_Action_Type', 'Last_Sys_Date'])
            
            final_summary = pd.merge(summary, sys_sum, on='Name', how='outer').fillna({'Count':0, 'Last_Message':'-', 'First_Action':'-', 'Action_History':'-'})
            is_exited = final_summary['Last_Action_Type'].str.contains('나갔습니다|내보냈습니다', na=False)

            # --- 결과 뷰 데이터 생성 ---
            df_curr = final_summary[~is_exited].drop(columns=['Last_Action_Type', 'Last_Sys_Date']).sort_values('Count', ascending=False)
            df_exit = final_summary[is_exited].sort_values('Last_Sys_Date', ascending=False).drop(columns=['Last_Action_Type', 'Last_Sys_Date'])
            df_sleep = final_summary[~is_exited].drop(columns=['Last_Action_Type', 'Last_Sys_Date']).sort_values('Last_Chat_Date', ascending=True)

            col_cfg = {
                "Last_Message": st.column_config.TextColumn("마지막 메시지", width="medium"),
                "Name": st.column_config.TextColumn("이름", width="medium"),
                "Action_History": st.column_config.TextColumn("활동 히스토리", width="medium"),
                "Count": st.column_config.NumberColumn("채팅수", width="small")
            }

            # --- [기능 부활] 엑셀 다운로드 파일 생성 ---
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_curr.to_excel(writer, sheet_name='현재 인원', index=False)
                df_exit.to_excel(writer, sheet_name='나간 인원', index=False)
                df_sleep.to_excel(writer, sheet_name='잠수 인원', index=False)
                df_final_master.to_excel(writer, sheet_name='Raw_Log', index=False)
            processed_data = output.getvalue()

            st.success(f"분석 완료! (총 {len(df_final_master):,}행 처리됨)")
            
            # 다운로드 버튼 노출 (화면 우측 정렬 효과를 위해 컬럼 사용)
            col1, col2 = st.columns([8, 2])
            with col2:
                st.download_button(
                    label="📥 엑셀 파일로 다운로드",
                    data=processed_data,
                    file_name=f"카카오톡_분석결과_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            
            # --- 탭 출력 ---
            tab1, tab2, tab3, tab4 = st.tabs([f"🟢 현재 인원 ({len(df_curr)}명)", f"🔴 나간 인원 ({len(df_exit)}명)", "💤 잠수 인원", "📝 Raw Log"])
            
            with tab1:
                st.dataframe(df_curr, width='stretch', hide_index=True, column_config=col_cfg)
            with tab2:
                st.dataframe(df_exit, width='stretch', hide_index=True, column_config=col_cfg)
            with tab3:
                st.dataframe(df_sleep, width='stretch', hide_index=True, column_config=col_cfg)
            with tab4:
                st.dataframe(df_final_master, width='stretch', hide_index=True)