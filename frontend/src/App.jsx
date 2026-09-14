import { useState, useRef } from "react";
import axios from "axios";
import "./App.css";

const API_BASE = "http://127.0.0.1:8000";

function App() {
  const [file, setFile] = useState(null);
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(false);
  const canvasRef = useRef(null);

  const handleFileChange = (e) => {
    setFile(e.target.files[0]);
    setResult(null);
  };

  const drawEvidenceBox = (imageBase64, box) => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    const img = new Image();
    img.onload = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

      const scale = canvas.width / 64;
      ctx.strokeStyle = "red";
      ctx.lineWidth = 3;
      ctx.strokeRect(
        box.x0 * scale,
        box.y0 * scale,
        (box.x1 - box.x0) * scale,
        (box.y1 - box.y0) * scale
      );
    };
    img.src = "data:image/png;base64," + imageBase64;
  };

  const handleSubmit = async () => {
    if (!file || !question) {
      alert("Please select a .tif file and enter a question.");
      return;
    }
    setLoading(true);
    const formData = new FormData();
    formData.append("file", file);
    formData.append("question", question);

    try {
      const res = await axios.post(`${API_BASE}/query`, formData);
      setResult(res.data);
      setTimeout(() => drawEvidenceBox(res.data.image_base64, res.data.evidence.region.box), 100);
      fetchHistory();
    } catch (err) {
      alert("Error: " + err.message);
    }
    setLoading(false);
  };

  const fetchHistory = async () => {
    const res = await axios.get(`${API_BASE}/history`);
    setHistory(res.data);
  };

  return (
    <div style={{ maxWidth: 700, margin: "40px auto", fontFamily: "sans-serif" }}>
      <h1>SatQuery AI</h1>
      <p>Upload a 13-band EuroSAT .tif image and ask a question.</p>

      <div style={{ marginBottom: 15 }}>
        <input type="file" accept=".tif" onChange={handleFileChange} />
      </div>

      <div style={{ marginBottom: 15 }}>
        <input
          type="text"
          placeholder="e.g. Is there water here?"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          style={{ width: "100%", padding: 8 }}
        />
      </div>

      <button onClick={handleSubmit} disabled={loading} style={{ padding: "8px 16px" }}>
        {loading ? "Analyzing..." : "Ask"}
      </button>

      {result && (
        <div style={{ marginTop: 30, border: "1px solid #ccc", padding: 20, borderRadius: 8 }}>
          <h3>Answer</h3>
          <p>{result.answer}</p>

          <div style={{ display: "flex", gap: 20, alignItems: "flex-start" }}>
            <div>
              <p>Evidence region (red box):</p>
              <canvas ref={canvasRef} width={256} height={256} style={{ border: "1px solid #999" }} />
            </div>
            <div>
              <p><b>Class:</b> {result.evidence.class}</p>
              <p><b>Confidence:</b> {(result.evidence.confidence * 100).toFixed(1)}%</p>
              <p><b>NDVI mean:</b> {result.evidence.ndvi_mean.toFixed(3)}</p>
              <p><b>NDWI mean:</b> {result.evidence.ndwi_mean.toFixed(3)}</p>
            </div>
          </div>
        </div>
      )}

      <div style={{ marginTop: 40 }}>
        <h3>Query History</h3>
        <button onClick={fetchHistory}>Refresh History</button>
        <ul>
          {history.map((h) => (
            <li key={h.id} style={{ marginBottom: 10 }}>
              <b>{h.filename}</b> — "{h.question}" → {h.answer}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export default App;