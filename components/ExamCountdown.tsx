import React, { useState, useEffect } from 'react';

const ExamCountdown = () => {
  const [days, setDays] = useState<number>(0);

  useEffect(() => {
    // 2027年の共通テスト（例として1月16日を設定。実際の日程に合わせて修正してください）
    const targetDate = new Date('2027-01-16T00:00:00+09:00');
    
    const updateCountdown = () => {
      const now = new Date();
      const diff = targetDate.getTime() - now.getTime();
      const remainDays = Math.ceil(diff / (1000 * 60 * 60 * 24));
      setDays(remainDays > 0 ? remainDays : 0);
    };

    updateCountdown();
    const timer = setInterval(updateCountdown, 1000 * 60 * 60); // 1時間ごとに更新
    return () => clearInterval(timer);
  }, []);

  return (
    <div style={{
      position: 'fixed',
      top: '20px',
      left: '20px',
      color: '#ff0000', // 赤文字
      fontWeight: 'bold',
      fontSize: '24px',
      zIndex: 1000,
      fontFamily: 'serif'
    }}>
      共通テストまで残り {days} 日
    </div>
  );
};

export default ExamCountdown;

