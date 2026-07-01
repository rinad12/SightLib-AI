import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  BookOpen, 
  Camera, 
  Search, 
  Sparkles, 
  Plus, 
  X, 
  Check, 
  Compass, 
  Loader2, 
  Layers, 
  User, 
  Info,
  BookMarked
} from 'lucide-react';

const API_BASE = 'http://127.0.0.1:8000/api'; // Connects to the local runner/playground backend
const USER_ID = 'default-user';

// Color palette for the skeuomorphic book spines
const SPINE_COLORS = [
  'bg-gradient-to-r from-red-800 to-red-950 border-red-700',
  'bg-gradient-to-r from-blue-800 to-blue-950 border-blue-700',
  'bg-gradient-to-r from-emerald-800 to-emerald-950 border-emerald-700',
  'bg-gradient-to-r from-amber-800 to-amber-950 border-amber-700',
  'bg-gradient-to-r from-indigo-800 to-indigo-950 border-indigo-700',
  'bg-gradient-to-r from-purple-800 to-purple-950 border-purple-700',
  'bg-gradient-to-r from-rose-800 to-rose-950 border-rose-700',
  'bg-gradient-to-r from-teal-800 to-teal-950 border-teal-700',
  'bg-gradient-to-r from-slate-800 to-slate-950 border-slate-700',
];

export default function App() {
  const [library, setLibrary] = useState([]);
  const [loading, setLoading] = useState(false);
  const [agentRunning, setAgentRunning] = useState(false);
  
  // Modals and Forms
  const [selectedBook, setSelectedBook] = useState(null);
  const [showEditModal, setShowEditModal] = useState(false);
  const [editForm, setEditForm] = useState({ title: '', author: '', genre: '', description: '', status: 'unread' });
  const [isManualEntry, setIsManualEntry] = useState(false);
  
  // Search & Recommendations
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [recommendedBookIds, setRecommendedBookIds] = useState([]);
  const [quotaStatus, setQuotaStatus] = useState(null);
  
  // Scanning state
  const [scanningImage, setScanningImage] = useState(null);
  const fileInputRef = useRef(null);

  // Fetch user library on mount
  useEffect(() => {
    fetchLibrary();
  }, []);

  const fetchLibrary = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/library?user_id=${USER_ID}`);
      const data = await res.json();
      if (data.status === 'success') {
        setLibrary(data.items || []);
      }
    } catch (err) {
      console.error('Failed to fetch library:', err);
    } finally {
      setLoading(false);
    }
  };

  // 1. Photo Upload / OCR Pipeline
  const handlePhotoUpload = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async () => {
      const base64 = reader.result.split(',')[1];
      setScanningImage(reader.result);
      setAgentRunning(true);
      setSearchResults([]); // Clear search to focus on scan
      setRecommendedBookIds([]); // Clear recommendations

      try {
        const response = await fetch(`${API_BASE}/agent/run?user_id=${USER_ID}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prompt: 'Process this book cover photo',
            image_bytes: base64
          })
        });
        const data = await response.json();
        
        if (data.status === 'success' && data.draft_data) {
          const draft = data.draft_data;
          setEditForm({
            title: draft.title || '',
            author: draft.author || '',
            genre: draft.genre || '',
            description: draft.description || '',
            status: 'unread'
          });
          setIsManualEntry(false);
          setShowEditModal(true);
        } else if (data.status === 'manual_input_required' || !data.draft_data) {
          // Fallback to manual entry if OCR failed
          setEditForm({ title: '', author: '', genre: '', description: '', status: 'unread' });
          setIsManualEntry(true);
          setShowEditModal(true);
        } else if (data.status === 'quota_exceeded') {
          setQuotaStatus('Daily photo scan limit reached (Max 3/day). Please try again tomorrow.');
        }
      } catch (err) {
        console.error('OCR pipeline failed:', err);
        // Fallback to manual form
        setEditForm({ title: '', author: '', genre: '', description: '', status: 'unread' });
        setIsManualEntry(true);
        setShowEditModal(true);
      } finally {
        setAgentRunning(false);
        setScanningImage(null);
      }
    };
    reader.readAsDataURL(file);
  };

  // 2. Direct DB Save (confirm save from form)
  const handleSaveBook = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/books?user_id=${USER_ID}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editForm)
      });
      const data = await res.json();
      if (data.status === 'success') {
        setShowEditModal(false);
        fetchLibrary();
      }
    } catch (err) {
      console.error('Failed to save book:', err);
    } finally {
      setLoading(false);
    }
  };

  // Update book status from details modal
  const handleUpdateStatus = async (status) => {
    if (!selectedBook) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/books?user_id=${USER_ID}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: selectedBook.title,
          author: selectedBook.author,
          genre: selectedBook.genre,
          description: selectedBook.description,
          status: status
        })
      });
      const data = await res.json();
      if (data.status === 'success') {
        setSelectedBook(prev => ({ ...prev, status }));
        fetchLibrary();
      }
    } catch (err) {
      console.error('Failed to update status:', err);
    } finally {
      setLoading(false);
    }
  };

  // 3. Contextual Search
  const handleSearch = async (e, forceSurprise = false) => {
    if (e) e.preventDefault();
    const query = forceSurprise ? '' : searchQuery;
    if (!query && !forceSurprise && library.length === 0) {
      // Both empty
      setSearchResults([]);
      setQuotaStatus('Please enter a search term or add books to your library first.');
      return;
    }

    setAgentRunning(true);
    setSearchResults([]);
    setRecommendedBookIds([]);
    setQuotaStatus(null);

    const promptText = query ? `Search for ${query}` : 'Search (empty prompt)';

    try {
      const response = await fetch(`${API_BASE}/agent/run?user_id=${USER_ID}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: promptText })
      });
      const data = await response.json();
      
      if (data.status === 'success' && data.items) {
        setSearchResults(data.items);
      } else if (data.status === 'missing_context') {
        setQuotaStatus('No context. Enter a search term or add books to your shelf first.');
      } else if (data.status === 'quota_exceeded') {
        setQuotaStatus('Search quota exceeded (Max 3 searches/day).');
      }
    } catch (err) {
      console.error('Search failed:', err);
    } finally {
      setAgentRunning(false);
    }
  };

  // 4. Personalized Recommendations (highlight existing shelf)
  const handleGetRecommendations = async () => {
    setAgentRunning(true);
    setRecommendedBookIds([]);
    setSearchResults([]);
    setQuotaStatus(null);

    try {
      const response = await fetch(`${API_BASE}/agent/run?user_id=${USER_ID}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: 'Recommend some books based on my shelf' })
      });
      const data = await response.json();
      
      if (data.status === 'success' && data.items) {
        // Map recommended titles to matching IDs in current library
        const ids = data.items.map(rec => {
          const match = library.find(lib => lib.title.toLowerCase() === rec.title.toLowerCase());
          return match ? match.id : null;
        }).filter(Boolean);
        
        setRecommendedBookIds(ids);
        if (ids.length === 0) {
          setQuotaStatus('No match found for recommended items on your shelves.');
        }
      } else if (data.status === 'empty_library') {
        setQuotaStatus('Add some books to your shelf first to get shelf recommendations.');
      } else if (data.status === 'quota_exceeded') {
        setQuotaStatus('Recommendations quota exceeded (Max 5/day).');
      }
    } catch (err) {
      console.error('Recommendations failed:', err);
    } finally {
      setAgentRunning(false);
    }
  };

  // Helper to split books onto shelves (6 books per shelf)
  const booksPerShelf = 6;
  const shelvesCount = Math.max(2, Math.ceil(library.length / booksPerShelf));
  const shelves = Array.from({ length: shelvesCount }, (_, index) => {
    return library.slice(index * booksPerShelf, (index + 1) * booksPerShelf);
  });

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-900 via-slate-950 to-zinc-950 text-slate-100 flex flex-col font-sans selection:bg-amber-600 selection:text-white pb-16">
      
      {/* Decorative top lights */}
      <div className="absolute top-0 left-1/4 w-96 h-32 bg-amber-500/10 rounded-full blur-3xl"></div>
      <div className="absolute top-0 right-1/4 w-96 h-32 bg-blue-500/10 rounded-full blur-3xl"></div>

      {/* Header */}
      <header className="max-w-7xl mx-auto w-full px-6 pt-8 pb-4 flex flex-col md:flex-row justify-between items-center border-b border-slate-800/80 gap-4 relative z-10">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-amber-600/15 border border-amber-500/30 rounded-xl text-amber-500 shadow-lg shadow-amber-500/5">
            <Layers className="w-8 h-8" />
          </div>
          <div>
            <h1 className="text-3xl font-serif tracking-wide text-transparent bg-clip-text bg-gradient-to-r from-amber-400 via-amber-200 to-yellow-500 font-bold">
              GridShelf AI
            </h1>
            <p className="text-xs text-slate-400 font-mono">Headless Agent & Skeuomorphic Library</p>
          </div>
        </div>

        {/* Global Control Buttons */}
        <div className="flex flex-wrap items-center gap-3">
          <input 
            type="file" 
            ref={fileInputRef} 
            onChange={handlePhotoUpload} 
            accept="image/*" 
            className="hidden" 
            id="book-cover-upload"
            name="book-cover-upload"
            aria-label="Upload book cover image"
          />
          
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={agentRunning || loading}
            className="flex items-center gap-2 px-4 py-2.5 bg-gradient-to-r from-amber-600 to-amber-700 hover:from-amber-500 hover:to-amber-600 disabled:opacity-50 text-slate-950 font-semibold rounded-xl transition duration-200 active:scale-95 shadow-lg shadow-amber-600/10"
          >
            {agentRunning && scanningImage ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Camera className="w-5 h-5" />
            )}
            Scan Cover
          </button>

          <button
            onClick={() => {
              setEditForm({ title: '', author: '', genre: '', description: '', status: 'unread' });
              setIsManualEntry(true);
              setShowEditModal(true);
            }}
            className="flex items-center gap-2 px-4 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700/60 font-semibold rounded-xl transition duration-200 active:scale-95"
          >
            <Plus className="w-5 h-5" />
            Add Manually
          </button>

          <button
            onClick={handleGetRecommendations}
            disabled={agentRunning || library.length === 0}
            className="flex items-center gap-2 px-4 py-2.5 bg-indigo-600/20 hover:bg-indigo-600/30 text-indigo-400 border border-indigo-500/30 disabled:opacity-50 font-semibold rounded-xl transition duration-200 active:scale-95 shadow-md shadow-indigo-600/5"
          >
            <Sparkles className="w-5 h-5" />
            What to Read Next?
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="max-w-7xl mx-auto w-full px-6 mt-8 flex flex-col lg:flex-row gap-8 relative z-10">
        
        {/* Left Side: Bookshelf Area (Skeuomorphic) */}
        <div className="flex-1 flex flex-col gap-12">
          
          {quotaStatus && (
            <div className="p-4 bg-red-950/30 border border-red-500/20 text-red-300 rounded-xl flex items-center gap-3">
              <Info className="w-5 h-5 flex-shrink-0" />
              <p className="text-sm font-medium">{quotaStatus}</p>
            </div>
          )}

          {/* Shelves Container */}
          <div className="bg-slate-900/40 border border-slate-800/60 p-8 rounded-3xl shadow-2xl backdrop-blur-md">
            
            {library.length === 0 ? (
              <div className="py-20 text-center flex flex-col items-center justify-center">
                <BookOpen className="w-16 h-16 text-slate-700 stroke-[1.5] mb-4" />
                <h3 className="text-xl font-serif text-slate-400">Your Bookshelf is Empty</h3>
                <p className="text-sm text-slate-500 mt-2 max-w-sm">
                  Click <b>Scan Cover</b> to upload a photo of a book, or <b>Add Manually</b> to place your first book spine here.
                </p>
              </div>
            ) : (
              <div className="flex flex-col gap-12">
                {shelves.map((shelfBooks, sIdx) => (
                  <div key={sIdx} className="relative flex flex-col bookshelf-perspective">
                    
                    {/* Books on the shelf */}
                    <div className="h-44 flex items-end px-8 gap-4 justify-start overflow-visible z-10">
                      {shelfBooks.map((book) => {
                        const isRecommended = recommendedBookIds.includes(book.id);
                        const spineColor = SPINE_COLORS[Math.abs(book.title.charCodeAt(0) + book.title.charCodeAt(1 || 0)) % SPINE_COLORS.length];
                        
                        return (
                          <motion.div
                            key={book.id}
                            onClick={() => setSelectedBook(book)}
                            className="relative cursor-pointer group overflow-visible"
                            style={{ transformOrigin: 'bottom center' }}
                            whileHover={{ y: -15, scale: 1.03 }}
                          >
                            {/* Glow if recommended */}
                            {isRecommended && (
                              <div className="absolute -inset-2 bg-indigo-500/30 blur-lg rounded-md animate-pulse"></div>
                            )}

                            {/* Book Spine */}
                            <div className={`w-12 h-36 ${spineColor} rounded-t-sm shadow-md border-l-2 border-t border-r border-slate-900 flex flex-col items-center justify-between py-4 select-none relative transition duration-300 group-hover:shadow-2xl`}>
                              
                              {/* Status indicator on top of spine */}
                              <div className="w-1.5 h-1.5 rounded-full flex-shrink-0">
                                {book.status === 'read' && <div className="w-full h-full bg-emerald-400 rounded-full"></div>}
                                {book.status === 'reading' && <div className="w-full h-full bg-amber-400 rounded-full"></div>}
                                {book.status === 'unread' && <div className="w-full h-full bg-slate-500 rounded-full"></div>}
                              </div>

                              {/* Title (vertical) */}
                              <p className="text-[10px] font-bold tracking-wider text-slate-200/90 whitespace-nowrap overflow-hidden text-ellipsis uppercase max-w-[100px]" style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)' }}>
                                {book.title}
                              </p>

                              {/* Decorative stripes at the bottom */}
                              <div className="flex flex-col gap-1 w-full px-2 opacity-50">
                                <div className="h-0.5 bg-slate-200"></div>
                                <div className="h-0.5 bg-slate-200"></div>
                              </div>
                            </div>
                          </motion.div>
                        );
                      })}
                    </div>

                    {/* Physical Shelf (Skeuomorphic wooden bar) */}
                    <div className="h-4 wooden-shelf w-full rounded-md z-0 shadow-lg relative">
                      {/* Shelf shadow underneath */}
                      <div className="absolute -bottom-4 left-0 right-0 h-4 bg-gradient-to-b from-black/40 to-transparent"></div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right Side: Search / Discovery / Side Panel */}
        <div className="w-full lg:w-96 flex flex-col gap-6">
          
          {/* Discovery / Search Bar */}
          <div className="bg-slate-900/40 border border-slate-800/60 p-6 rounded-3xl shadow-xl backdrop-blur-md">
            <h3 className="text-lg font-serif font-bold text-amber-500 mb-4 flex items-center gap-2">
              <Compass className="w-5 h-5" />
              Discover New Books
            </h3>

            <form onSubmit={handleSearch} className="flex gap-2">
              <div className="relative flex-1">
                <input
                  type="text"
                  placeholder="e.g. Cyberpunk 1980s..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full bg-slate-950/80 border border-slate-800 rounded-xl py-2 px-3 pl-9 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:border-amber-500 transition duration-200"
                  id="book-search-input"
                  name="book-search"
                  aria-label="Search or discover books"
                />
                <Search className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
              </div>
              <button 
                type="submit"
                disabled={agentRunning}
                className="bg-amber-600 hover:bg-amber-500 disabled:bg-amber-700 text-slate-950 p-2.5 rounded-xl transition duration-200"
              >
                <Search className="w-4 h-4 font-bold" />
              </button>
            </form>

            <button
              onClick={() => handleSearch(null, true)}
              disabled={agentRunning}
              className="mt-3 w-full flex items-center justify-center gap-2 py-2 px-4 bg-slate-800 hover:bg-slate-700 border border-slate-700/50 rounded-xl text-xs font-semibold text-slate-300 transition duration-200"
            >
              <Sparkles className="w-3.5 h-3.5 text-amber-500" />
              Surprise Me (Discovery Mode)
            </button>
          </div>

          {/* Discovery Shelf / Search Results */}
          {searchResults.length > 0 && (
            <div className="bg-slate-900/40 border border-slate-850/60 p-6 rounded-3xl shadow-xl backdrop-blur-md">
              <h3 className="text-md font-serif font-bold text-slate-300 mb-4">Books Found Online:</h3>
              <div className="flex flex-col gap-3">
                {searchResults.map((book, idx) => (
                  <div 
                    key={idx} 
                    onClick={() => {
                      setEditForm({
                        title: book.title || '',
                        author: book.author || '',
                        genre: book.genre || '',
                        description: book.description || '',
                        status: 'unread'
                      });
                      setIsManualEntry(false);
                      setShowEditModal(true);
                    }}
                    className="p-3 bg-slate-950/60 border border-slate-850 hover:border-amber-500/40 rounded-xl cursor-pointer transition duration-200 group flex items-start gap-3"
                  >
                    <BookMarked className="w-5 h-5 text-slate-500 group-hover:text-amber-500 flex-shrink-0 mt-0.5" />
                    <div>
                      <h4 className="text-sm font-semibold text-slate-200 group-hover:text-amber-500 line-clamp-1">
                        {book.title}
                      </h4>
                      <p className="text-xs text-slate-400 mt-0.5">{book.author}</p>
                      {book.genre && (
                        <span className="inline-block mt-1.5 px-2 py-0.5 bg-slate-800 text-[10px] text-slate-400 rounded-md">
                          {book.genre}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </main>

      {/* Loading Scan Overlay */}
      {agentRunning && scanningImage && (
        <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-md z-50 flex flex-col items-center justify-center">
          <div className="relative w-64 h-80 bg-slate-900 border-2 border-amber-500/40 rounded-2xl overflow-hidden shadow-2xl">
            <img src={scanningImage} className="w-full h-full object-cover opacity-60" alt="Scanning cover" />
            {/* Red laser animation */}
            <motion.div 
              className="absolute left-0 right-0 h-1 bg-red-500 shadow-[0_0_8px_#ef4444]"
              animate={{ top: ['0%', '100%', '0%'] }}
              transition={{ repeat: Infinity, duration: 2.5, ease: 'linear' }}
            />
          </div>
          <div className="mt-8 text-center">
            <h3 className="text-xl font-serif text-slate-200 flex items-center justify-center gap-2">
              <Loader2 className="w-5 h-5 animate-spin text-amber-500" />
              Scanning Cover...
            </h3>
            <p className="text-sm text-slate-400 mt-2">Gemini 3.1 Pro is performing OCR & metadata enrichment</p>
          </div>
        </div>
      )}

      {/* Book Details Modal */}
      <AnimatePresence>
        {selectedBook && (
          <div 
            onClick={() => setSelectedBook(null)}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 flex items-center justify-center p-4 cursor-pointer"
          >
            <motion.div
              onClick={(e) => e.stopPropagation()}
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-slate-900 border border-slate-800 w-full max-w-lg rounded-3xl shadow-2xl p-6 relative overflow-hidden cursor-default"
            >
              {/* Cover background glow */}
              <div className="absolute top-0 right-0 w-32 h-32 bg-amber-500/10 rounded-full blur-2xl"></div>

              <div className="flex justify-between items-start gap-4">
                <div>
                  <h2 className="text-2xl font-serif font-bold text-slate-100">{selectedBook.title}</h2>
                  <p className="text-slate-400 font-semibold mt-1">by {selectedBook.author}</p>
                </div>
                <button 
                  type="button"
                  id="close-details-btn"
                  onClick={() => setSelectedBook(null)}
                  className="p-1.5 bg-slate-800 hover:bg-slate-700 text-slate-400 rounded-xl transition duration-150"
                  aria-label="Close details modal"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {selectedBook.genre && (
                <div className="mt-4 flex flex-wrap gap-2">
                  <span className="px-3 py-1 bg-amber-600/10 border border-amber-500/20 text-amber-500 text-xs font-semibold rounded-full">
                    {selectedBook.genre}
                  </span>
                </div>
              )}

              <div className="mt-6 border-t border-slate-800/80 pt-4">
                <h4 className="text-xs font-mono uppercase text-slate-500">Synopsis</h4>
                <p className="text-slate-300 text-sm mt-2 leading-relaxed">
                  {selectedBook.description || 'No description available.'}
                </p>
              </div>

              {/* Status Selectors */}
              <div className="mt-6 border-t border-slate-800/80 pt-4">
                <h4 className="text-xs font-mono uppercase text-slate-500 mb-3">Reading Status</h4>
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { key: 'unread', label: 'Unread', color: 'bg-slate-800 hover:bg-slate-750 text-slate-300 border-slate-750' },
                    { key: 'reading', label: 'Reading', color: 'bg-amber-600/10 hover:bg-amber-600/15 text-amber-500 border-amber-500/30' },
                    { key: 'read', label: 'Completed', color: 'bg-emerald-600/10 hover:bg-emerald-600/15 text-emerald-500 border-emerald-500/30' }
                  ].map((btn) => {
                    const active = selectedBook.status === btn.key;
                    return (
                      <button
                        key={btn.key}
                        onClick={() => handleUpdateStatus(btn.key)}
                        className={`py-2 px-3 text-xs border font-semibold rounded-xl transition duration-150 ${active ? 'bg-amber-600 text-slate-950 border-amber-600' : btn.color}`}
                      >
                        {btn.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* Edit Form Modal (HITL Draft & Manual Entry) */}
      <AnimatePresence>
        {showEditModal && (
          <div 
            onClick={() => setShowEditModal(false)}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40 flex items-center justify-center p-4 cursor-pointer"
          >
            <motion.div
              onClick={(e) => e.stopPropagation()}
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-slate-900 border border-slate-800 w-full max-w-md rounded-3xl shadow-2xl p-6 relative cursor-default"
            >
              <div className="flex justify-between items-center mb-6">
                <div>
                  <h2 className="text-xl font-serif font-bold text-slate-200">
                    {isManualEntry ? 'Add Manual Book' : 'Review Cover Draft'}
                  </h2>
                  <p className="text-xs text-slate-400 mt-1">
                    {isManualEntry ? 'Bypasses AI processing' : 'Please verify metadata fields'}
                  </p>
                </div>
                <button 
                  type="button"
                  id="close-edit-btn"
                  onClick={() => setShowEditModal(false)}
                  className="p-1.5 bg-slate-800 hover:bg-slate-700 text-slate-400 rounded-xl transition duration-150"
                  aria-label="Close edit modal"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <form onSubmit={handleSaveBook} className="space-y-4">
                <div>
                  <label htmlFor="book-title-input" className="block text-xs font-mono uppercase text-slate-400 mb-1.5">Book Title</label>
                  <input
                    type="text"
                    required
                    id="book-title-input"
                    name="title"
                    value={editForm.title}
                    onChange={(e) => setEditForm(prev => ({ ...prev, title: e.target.value }))}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl py-2 px-3 text-sm text-slate-100 focus:outline-none focus:border-amber-500"
                  />
                </div>

                <div>
                  <label htmlFor="book-author-input" className="block text-xs font-mono uppercase text-slate-400 mb-1.5">Author</label>
                  <input
                    type="text"
                    required
                    id="book-author-input"
                    name="author"
                    value={editForm.author}
                    onChange={(e) => setEditForm(prev => ({ ...prev, author: e.target.value }))}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl py-2 px-3 text-sm text-slate-100 focus:outline-none focus:border-amber-500"
                  />
                </div>

                <div>
                  <label htmlFor="book-genre-input" className="block text-xs font-mono uppercase text-slate-400 mb-1.5">Genre</label>
                  <input
                    type="text"
                    id="book-genre-input"
                    name="genre"
                    value={editForm.genre}
                    onChange={(e) => setEditForm(prev => ({ ...prev, genre: e.target.value }))}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl py-2 px-3 text-sm text-slate-100 focus:outline-none focus:border-amber-500"
                  />
                </div>

                <div>
                  <label htmlFor="book-description-input" className="block text-xs font-mono uppercase text-slate-400 mb-1.5">Description / Synopsis</label>
                  <textarea
                    rows={3}
                    id="book-description-input"
                    name="description"
                    value={editForm.description}
                    onChange={(e) => setEditForm(prev => ({ ...prev, description: e.target.value }))}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl py-2 px-3 text-sm text-slate-100 focus:outline-none focus:border-amber-500 resize-none"
                  />
                </div>

                <div className="pt-4 flex gap-3">
                  <button
                    type="button"
                    onClick={() => setShowEditModal(false)}
                    className="flex-1 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 font-semibold rounded-xl transition duration-150"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="flex-1 py-2.5 bg-amber-600 hover:bg-amber-500 text-slate-950 font-bold rounded-xl transition duration-150 shadow-lg shadow-amber-600/10"
                  >
                    Save to Shelf
                  </button>
                </div>
              </form>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

    </div>
  );
}
