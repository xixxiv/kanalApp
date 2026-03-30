import streamlit as st
import re
import pandas as pd
from datetime import datetime
import io
import zipfile  # ZIP 처리를 위해 필수 추가

# --- 웹 페이지 기본 설정 ---
st.set_page_config(page_title="카카오톡 단톡방 분석기", layout="wide", page_icon="📊")
st.title("📊 카카오톡 단톡방 인원 및 활동 분석기")

# --- 메시지 정규화 함수 (중복 매칭용) ---
def normalize_msg(msg):
    msg = re.sub(r'\(?(이모티콘|Emoticons)\)?', '', msg)
    msg = re.sub(r'^이모티콘\s+', '', msg)
    msg = msg.replace("'일정 취소'", "'일정 삭제'").strip()
    return msg

# --- 코어 파싱 로직 ---
def parse_kakao_file(file_content):
    data = []
    # 정규식 패턴 설정
    date_pattern_1 = re.compile(r"^-+ (\d{4})년 (\d{1,2})월 (\d{1,2})일 .*-+$") 
    date_pattern_2 = re.compile(r"^(\d{4})년 (\d{1,2})월 (\d{1,2})일 [월화수목금토일]요일$") 
    chat_pc = re.compile(r"^\[(.*?)\] \[(오전|오후) (\d{1,2}):(\d{1,2})\] (.*)$")
    chat_ios = re.compile(r"^(\d{4})\. ?(\d{1,2})\. ?(\d{1,2})\. (?:(오전|오후) )?(\d{1,2}):(\d{1,2}), (.*?) : (.*)$")
    chat_and = re.compile(r"^(\d{4})년 (\d{1,2})월 (\d{1,2})일 (오전|오후) (\d{1,2}):(\d{1,2}), (.*?) : (.*)$")
    hidden_msg_text = "관리자가 메시지를 가렸습니다."
    hidden_msg_ios = re.compile(r"^(\d{4})\. ?(\d{1,2})\. ?(\d{1,2})\. (?:(오전|오후) )?(\d{1,2}):(\d{1,2}): (관리자가 메시지를 가렸습니다\.)$")
    sys_action_pattern = r"(들어왔습니다\.|나갔습니다\.|내보냈습니다\.)"
    sys_pc = re.compile(rf"^(.*?)(님이|님을) {sys_action_pattern}")
    sys_ios = re.compile(rf"^(\d{{4}})\. ?(\d{{1,2}})\. ?(\d{{1,2}})\. (?:(오전|오후) )?(\d{{1,2}}):(\d{{1,2}})[,:] (.*?)(님이|님을) {sys_action_pattern}")
    sys_and = re.compile(rf"^(\d{{4}})년 (\d{{1,2}})월 (\d{{1,2}})일 (오전|오후) (\d{{1,2}}):(\d{{1,2}}), (.*?)(님이|님을) {sys_action_pattern}")
    valid_sys_combos = [("님이", "들어왔습니다."), ("님이", "나갔습니다."), ("님을", "내보냈습니다.")]

    current_date = None
    last_seen_minute_key = None
    ms_offset = 0  
    lines = file_content.splitlines()
    
    for line in lines:
        line_clean = line.strip()
        if not line_clean: continue
        match_date = date_pattern_1.match(line_clean) or date_pattern_2.match(line_clean)
        if match_date:
            y, m, d = match_date.groups()
            current_date = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
            last_seen_minute_key = None; ms_offset = 0
            continue
        
        m_hidden_ios = hidden_msg_ios.match(line_clean)
        if m_hidden_ios or hidden_msg_text in line_clean:
            if m_hidden_ios:
                y, m, d, ampm, h, mnt, _ = m_hidden_ios.groups()
                hour = int(h)
                if ampm == '오후' and hour != 12: hour += 12
                if ampm == '오전' and hour == 12: hour = 0
                minute_key = f"{current_date} {hour:02d}:{mnt.zfill(2)}"
            else: minute_key = last_seen_minute_key if last_seen_minute_key else f"{current_date} 00:00"
            if minute_key == last_seen_minute_key: ms_offset += 1
            else: last_seen_minute_key = minute_key; ms_offset = 0
            time_str = f"{minute_key[-5:]}:00.{ms_offset:03d}"
            data.append({'Datetime': pd.to_datetime(f"{current_date} {time_str}"), 'Date': current_date, 'Name': '시스템', 'Message': hidden_msg_text, 'Type': 'Chat', 'Source': 'iPhone' if m_hidden_ios else 'PC'})
            continue

        m_pc = chat_pc.match(line_clean); m_ios = chat_ios.match(line_clean); m_and = chat_and.match(line_clean)
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
            data.append({'Datetime': pd.to_datetime(f"{current_date} {time_str}"), 'Date': current_date, 'Name': name, 'Message': msg, 'Type': 'Chat', 'Source': 'iPhone' if m_ios else ('Android' if m_and else 'PC')})
            continue

        m_sys_ios = sys_ios.match(line_clean); m_sys_and = sys_and.match(line_clean); m_sys_pc = sys_pc.match(line_clean)
        if m_sys_ios or m_sys_and:
            y, m, d, ampm, h, mnt, name, josa, action = (m_sys_ios or m_sys_and).groups()
            if (josa, action) in valid_sys_combos:
                current_date = f"{y}-{m.zfill(2)}-{d.zfill(2)}"; hour = int(h)
                if ampm == '오후' and hour != 12: hour += 12
                if ampm == '오전' and hour == 12: hour = 0
                minute_key = f"{current_date} {hour:02d}:{mnt.zfill(2)}"
                if minute_key == last_seen_minute_key: ms_offset += 1
                else: last_seen_minute_key = minute_key; ms_offset = 0
                time_str = f"{minute_key[-5:]}:00.{ms_offset:03d}"
                data.append({'Datetime': pd.to_datetime(f"{current_date} {time_str}"), 'Date': current_date, 'Name': name, 'Message': f"{name}{josa} {action}", 'Type': 'System', 'Source': 'iPhone' if m_sys_ios else 'Android'})
            continue
        elif m_sys_pc:
            name, josa, action = m_sys_pc.groups()
            if (josa, action) in valid_sys_combos and current_date and len(name) < 40: 
                minute_key = last_seen_minute_key if last_seen_minute_key else f"{current_date} 00:00"
                if minute_key == last_seen_minute_key: ms_offset += 1
                else: last_seen_minute_key = minute_key; ms_offset = 0
                time_str = f"{minute_key[-5:]}:00.{ms_offset:03d}"
                data.append({'Datetime': pd.to_datetime(f"{current_date} {time_str}"), 'Date': current_date, 'Name': name, 'Message': f"{name}{josa} {action}", 'Type': 'System', 'Source': 'PC'})
            continue

        if data and data[-1]['Type'] == 'Chat':
            data[-1]['Message'] += '\n' + line.replace('\r', '').replace('\n', '')
    return pd.DataFrame(data)

# --- 웹 인터페이스 ---
st.markdown("### 📂 파일 업로드")
# 이 변수가 반드시 정의되어야 NameError가 발생하지 않습니다.
uploaded_files = st.file_uploader("카카오톡 텍스트(.txt) 또는 압축파일(.zip)을 업로드하세요.", type=["txt", "zip"], accept_multiple_files=True)

if uploaded_files:
    if st.button("분석 시작", type="primary"):
        with st.spinner("데이터 분석 및 병합 중..."):
            df_list = []
            for uf in uploaded_files:
                # ZIP 파일 처리
                if uf.name.lower().endswith('.zip'):
                    try:
                        with zipfile.ZipFile(uf) as z:
                            txt_files = [f for f in z.namelist() if f.lower().endswith('.txt')]
                            for t_file in txt_files:
                                with z.open(t_file) as f:
                                    content = f.read().decode('utf-8-sig')
                                    df_list.append(parse_kakao_file(content))
                    except Exception as e:
                        st.error(f"ZIP 파일을 읽는 중 에러: {uf.name} ({e})")
                # TXT 파일 처리
                elif uf.name.lower().endswith('.txt'):
                    content = uf.read().decode('utf-8-sig')
                    df_list.append(parse_kakao_file(content))
            
            df_combined = pd.concat([d for d in df_list if not d.empty], ignore_index=True)
            if df_combined.empty: st.stop()

            # --- 병합 및 중복 제거 ---
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
            
# --- (중략) ---

            # 집계 생성
            summary = df_chat_cleaned[df_chat_cleaned['Name'] != '시스템'].groupby('Name').agg(Last_Chat_Date=('Datetime', 'max'), Last_Message=('Message', 'last'), Count=('Message', 'count')).reset_index()
            
            def get_history(x):
                x = x.sort_values('Datetime')
                # 입장, 퇴장, 강퇴 메시지 리스트 생성
                actions = [f"[{row['Date']}] 입장" if "들어왔습니다" in row['Message'] else (f"[{row['Date']}] 퇴장" if "나갔습니다" in row['Message'] else f"[{row['Date']}] 강퇴") 
                           for _, row in x.iterrows() if any(k in row['Message'] for k in ["들어왔습니다", "나갔습니다", "내보냈습니다"])]
                
                if not actions:
                    return pd.Series({'First_Action': '-', 'Action_History': '-', 'Last_Action_Type': x.iloc[-1]['Message']})
                
                # [수정된 로직]
                # 첫 번째 기록이 '입장'인 경우 -> 최초 입장에 기록하고 나머지를 히스토리에 배치
                if "입장" in actions[0]:
                    first = actions[0]
                    history_list = actions[1:]
                # 첫 번째 기록이 '입장'이 아닌 경우 (로그 중간부터 기록된 경우) -> 최초 입장은 '-'로 두고 모든 기록을 히스토리에 배치
                else:
                    first = '-'
                    history_list = actions[:]
                
                # 히스토리는 최신순으로 보여주기 위해 역순 정렬
                history = '\n'.join(history_list[::-1]) if history_list else '-'
                
                return pd.Series({'First_Action': first, 'Action_History': history, 'Last_Action_Type': x.iloc[-1]['Message']})
            
            # include_groups=False를 추가하여 경고 방지
            sys_sum = df_sys_cleaned.groupby('Name').apply(get_history, include_groups=False).reset_index() if not df_sys_cleaned.empty else pd.DataFrame(columns=['Name', 'First_Action', 'Action_History', 'Last_Action_Type'])

# --- (이하 동일) ---

            df_curr = final_summary[~is_exited].drop(columns=['Last_Action_Type']).sort_values('Count', ascending=False)
            df_exit = final_summary[is_exited].drop(columns=['Last_Action_Type']).sort_values('Count', ascending=False)
            df_sleep = final_summary[~is_exited].drop(columns=['Last_Action_Type']).sort_values('Last_Chat_Date', ascending=True)

            col_cfg = {
                "Last_Message": st.column_config.TextColumn("마지막 메시지", width="medium"),
                "Name": st.column_config.TextColumn("이름", width="medium"),
                "Action_History": st.column_config.TextColumn("활동 히스토리", width="medium")
            }

            st.success(f"분석 완료! (총 {len(df_final_master)}행)")
            tab1, tab2, tab3, tab4 = st.tabs([f"🟢 현재 인원 ({len(df_curr)}명)", f"🔴 나간 인원 ({len(df_exit)}명)", "💤 잠수 인원", "📝 Raw Log"])
            
            with tab1: st.dataframe(df_curr, width='stretch', hide_index=True, column_config=col_cfg)
            with tab2: st.dataframe(df_exit, width='stretch', hide_index=True, column_config=col_cfg)
            with tab3: st.dataframe(df_sleep, width='stretch', hide_index=True, column_config=col_cfg)
            with tab4: st.dataframe(df_final_master, width='stretch', hide_index=True)